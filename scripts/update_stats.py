"""Refresh committed SVGs; a failed fetch leaves all existing assets intact."""
import datetime as dt
import html
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request

USER = 'imgunjan'
ROOT = Path(__file__).resolve().parents[1]

def fetch(url):
    headers = {'User-Agent': 'imgunjan-profile'}
    if url.startswith('https://api.github.com/') and os.getenv('GH_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['GH_TOKEN']
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=45) as r:
        return json.load(r)

def paged(url):
    result = []
    for page in range(1, 1001):
        rows = fetch(url + ('&' if '?' in url else '?') + f'per_page=100&page={page}')
        result.extend(rows)
        if len(rows) < 100:
            return result
    raise RuntimeError('Pagination limit reached')

def text(x,y,value,size=14,color='#94a3b8'):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}">{html.escape(str(value))}</text>'

def svg(title,subtitle,body,height):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="960" height="{height}" viewBox="0 0 960 {height}" role="img"><title>{html.escape(title)}</title><rect width="960" height="{height}" rx="18" fill="#0d1117"/><rect x="1" y="1" width="958" height="{height-2}" rx="18" fill="none" stroke="#263344"/><g font-family="DejaVu Sans,Arial,sans-serif">{text(30,38,title,21,'#e6edf3')}{text(30,63,subtitle,12)}{body}</g></svg>'''

def streaks(days):
    longest = run = 0
    for d in days:
        run = run + 1 if d['count'] else 0
        longest = max(longest,run)
    relevant = days[:-1] if days and not days[-1]['count'] else days
    current = 0
    for d in reversed(relevant):
        if not d['count']: break
        current += 1
    return current,longest

def generate():
    profile = fetch(f'https://api.github.com/users/{USER}')
    repos = paged(f'https://api.github.com/users/{USER}/repos?type=owner')
    raw = fetch(f'https://github-contributions-api.jogruber.de/v4/{USER}?y=last')
    days = sorted(raw['contributions'],key=lambda d:d['date'])
    if not days or any(not isinstance(d['count'],int) or d['count'] < 0 for d in days):
        raise ValueError('Invalid contribution data')
    today = dt.datetime.now(dt.timezone.utc).date()
    if dt.date.fromisoformat(days[-1]['date']) < today-dt.timedelta(days=2):
        raise ValueError('Contribution data is stale')
    end = dt.date.fromisoformat(days[-1]['date'])
    dates = [end-dt.timedelta(days=i) for i in range(29,-1,-1)]
    counts = {d.isoformat():0 for d in dates}
    # Default-branch commits in owned public repositories; GitHub-linked author only.
    for repo in repos:
        if not repo['size']: continue
        query = urllib.parse.urlencode({'author':USER,'since':dates[0].isoformat()+'T00:00:00Z','until':end.isoformat()+'T23:59:59Z'})
        for commit in paged(repo['commits_url'].replace('{/sha}','')+'?'+query):
            date = commit['commit']['committer']['date'][:10]
            if date in counts: counts[date] += 1
    current,longest = streaks(days)
    updated = f'Public data · through {end.isoformat()} · refreshed {today.isoformat()}'
    metrics = [('PUBLIC REPOS',profile['public_repos']),('STARS RECEIVED',sum(r['stargazers_count'] for r in repos)),('FOLLOWERS',profile['followers']),('CONTRIBUTIONS',sum(d['count'] for d in days))]
    body = ''
    for i,(label,value) in enumerate(metrics):
        x = 30+i*232
        body += text(x,112,label,11)+text(x,156,value,34,'#67e8f9')
    assets = {'analytics.svg':svg('GitHub at a glance',updated,body,187)}
    body = ''
    for i,(label,value) in enumerate([('CURRENT STREAK',current),('LONGEST IN WINDOW',longest),('ACTIVE DAYS',sum(d['count']>0 for d in days))]):
        x=30+i*310
        body += text(x,111,label,11)+text(x,155,f'{value} days',30,'#a5b4fc')
    assets['streak.svg']=svg('Consistency over time','Streaks within the displayed contribution window; today may still be in progress.',body,187)
    colors=['#192535','#164e63','#0e7490','#22d3ee','#a5f3fc']
    body=''
    start=dt.date.fromisoformat(days[0]['date']); offset=(start.weekday()+1)%7
    for i,d in enumerate(days):
        n=i+offset; x=30+(n//7)*17; y=92+(n%7)*17
        level=min(4,max(0,d['level']))
        body+=f'<rect x="{x}" y="{y}" width="13" height="13" rx="3" fill="{colors[level]}"><title>{d["date"]}: {d["count"]} contributions</title></rect>'
    body+=text(30,237,days[0]['date'],11)+text(790,237,days[-1]['date'],11)
    assets['calendar.svg']=svg('Contribution calendar','Commits, issues, pull requests and other GitHub contributions — not commits alone.',body,260)
    def chart(title,sub,values,color):
        high=max(1,max(values)); body=''
        for tick in range(3):
            y=205-tick*55
            body+=f'<path d="M50 {y} H920" stroke="#263344"/>'+text(15,y+4,round(high*tick/2,1),10)
        points=' '.join(f'{50+i*30},{205-v/high*110:.1f}' for i,v in enumerate(values))
        body+=f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="3" stroke-linejoin="round"/>'
        for i,v in enumerate(values):
            body+=f'<circle cx="{50+i*30}" cy="{205-v/high*110:.1f}" r="3" fill="{color}"><title>{dates[i]}: {v}</title></circle>'
        body+=text(50,235,str(dates[0]),11)+text(810,235,str(dates[-1]),11)
        return svg(title,sub,body,260)
    bydate={d['date']:d['count'] for d in days}
    assets['activity.svg']=chart('Contribution activity · last 30 days','Daily contributions shown on the public GitHub calendar.',[bydate.get(str(d),0) for d in dates],'#22d3ee')
    assets['commits.svg']=chart('Commit activity · last 30 days','Owned public repositories · default branches · commit date (UTC) · merges included.',list(counts.values()),'#a5b4fc')
    # Finish fetching and rendering before replacing any existing cards.
    for name,content in assets.items():
        target=ROOT/'assets'/name
        temp=target.with_suffix('.tmp'); temp.write_text(content); temp.replace(target)
    print('Updated',len(assets),'cards')

if __name__ == '__main__': generate()
