"""
analytics.py — Pipeline d'analyse marketing pour Tracking Lab.

Modules :
  1. Extraction & ranking de hashtags
  2. Score de viralité par vidéo
  3. Détection de tendances émergentes
  4. Métriques de croissance (followers, engagement)
  5. Identification des contenus performants
  6. Insights marketing automatiques

Intégration : appelé par les crons pg_cron et les endpoints API.
"""

import re
import math
from datetime import datetime, timedelta, date
from collections import Counter

from database import get_connection, _fetchall, _fetchone, _execute, _q


# ──────────────────────────────────────────────
# 1. HASHTAG EXTRACTION & RANKING
# ──────────────────────────────────────────────

_HASHTAG_RE = re.compile(r'#(\w{2,50})', re.UNICODE)


def extract_hashtags(text):
    """Extrait les hashtags d'un texte (description de vidéo)."""
    if not text:
        return []
    return [tag.lower() for tag in _HASHTAG_RE.findall(text)]


def compute_hashtag_stats(user_id, days=30):
    """
    Calcule les stats de chaque hashtag sur les N derniers jours.
    Retourne une liste triée par score (usage × engagement moyen).
    """
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime('%Y-%m-%d')

    with get_connection() as conn:
        videos = _fetchall(conn, """
            SELECT description, views, likes, comments, shares, saves, platform,
                   create_time, video_id
            FROM videos
            WHERE user_id = %s AND create_time >= %s AND description IS NOT NULL
            ORDER BY create_time DESC
        """, (user_id, cutoff))

    hashtag_data = {}  # tag -> {count, total_views, total_engagement, platforms, videos}

    for v in videos:
        tags = extract_hashtags(v.get('description', ''))
        views = v.get('views', 0) or 0
        engagement = (v.get('likes', 0) or 0) + (v.get('comments', 0) or 0) + \
                     (v.get('shares', 0) or 0) + (v.get('saves', 0) or 0)
        platform = v.get('platform', 'tiktok')

        for tag in set(tags):  # set() pour dédupliquer dans une même vidéo
            if tag not in hashtag_data:
                hashtag_data[tag] = {
                    'count': 0, 'total_views': 0, 'total_engagement': 0,
                    'platforms': set(), 'first_seen': v.get('create_time'),
                    'last_seen': v.get('create_time'),
                }
            d = hashtag_data[tag]
            d['count'] += 1
            d['total_views'] += views
            d['total_engagement'] += engagement
            d['platforms'].add(platform)
            if v.get('create_time') and (not d['last_seen'] or str(v['create_time']) > str(d['last_seen'])):
                d['last_seen'] = v['create_time']

    # Calcul du score et tri
    results = []
    for tag, d in hashtag_data.items():
        avg_views = d['total_views'] / max(1, d['count'])
        avg_engagement = d['total_engagement'] / max(1, d['count'])
        eng_rate = (d['total_engagement'] / max(1, d['total_views'])) * 100

        # Score composite : fréquence × engagement moyen (log-scaled)
        score = d['count'] * math.log1p(avg_engagement) * (1 + eng_rate / 10)

        results.append({
            'hashtag': f'#{tag}',
            'count': d['count'],
            'total_views': d['total_views'],
            'avg_views': round(avg_views),
            'total_engagement': d['total_engagement'],
            'avg_engagement': round(avg_engagement),
            'engagement_rate': round(eng_rate, 2),
            'platforms': sorted(d['platforms']),
            'score': round(score, 1),
            'first_seen': str(d.get('first_seen', ''))[:10],
            'last_seen': str(d.get('last_seen', ''))[:10],
        })

    results.sort(key=lambda x: x['score'], reverse=True)
    return results


# ──────────────────────────────────────────────
# 2. SCORE DE VIRALITÉ
# ──────────────────────────────────────────────

def compute_virality_score(video):
    """
    Calcule un score de viralité (0-100) pour une vidéo.

    Facteurs :
    - Ratio views/followers (reach relatif)
    - Taux d'engagement (likes+comments+shares+saves / views)
    - Ratio shares/likes (potentiel de diffusion)
    - Vélocité (views par jour depuis publication)
    """
    views = video.get('views', 0) or 0
    likes = video.get('likes', 0) or 0
    comments = video.get('comments', 0) or 0
    shares = video.get('shares', 0) or 0
    saves = video.get('saves', 0) or 0
    followers = video.get('followers', 0) or 0

    if views == 0:
        return 0.0

    engagement = likes + comments + shares + saves

    # 1. Taux d'engagement (0-30 pts)
    eng_rate = engagement / views
    eng_score = min(30, eng_rate * 300)  # 10% engagement = 30 pts

    # 2. Reach relatif (0-25 pts) — views vs followers
    if followers > 0:
        reach_ratio = views / followers
        reach_score = min(25, math.log1p(reach_ratio) * 8)
    else:
        reach_score = min(25, math.log1p(views / 1000) * 5)

    # 3. Potentiel de diffusion (0-25 pts) — shares + saves ratio
    share_ratio = (shares + saves) / max(1, likes) if likes > 0 else 0
    share_score = min(25, share_ratio * 50)

    # 4. Vélocité (0-20 pts) — views par jour
    days_old = 1
    if video.get('create_time'):
        try:
            ct = video['create_time']
            if isinstance(ct, str):
                ct = datetime.fromisoformat(ct.replace('Z', '+00:00').split('+')[0])
            delta = (datetime.utcnow() - ct).days
            days_old = max(1, delta)
        except (ValueError, TypeError):
            pass

    velocity = views / days_old
    velocity_score = min(20, math.log1p(velocity / 100) * 6)

    total = eng_score + reach_score + share_score + velocity_score
    return round(min(100, total), 1)


def get_viral_videos(user_id, limit=20, days=30):
    """Retourne les vidéos triées par score de viralité."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime('%Y-%m-%d')

    with get_connection() as conn:
        videos = _fetchall(conn, """
            SELECT v.video_id, v.account_username, v.description, v.create_time,
                   v.views, v.likes, v.comments, v.shares, v.saves,
                   v.thumbnail_url, v.platform, v.duration,
                   a.followers
            FROM videos v
            LEFT JOIN accounts a ON a.username = v.account_username
                AND a.user_id = v.user_id AND a.platform = v.platform
            WHERE v.user_id = %s AND v.create_time >= %s
            ORDER BY v.views DESC
            LIMIT 200
        """, (user_id, cutoff))

    for v in videos:
        v['virality_score'] = compute_virality_score(v)

    videos.sort(key=lambda x: x['virality_score'], reverse=True)
    return videos[:limit]


# ──────────────────────────────────────────────
# 3. DÉTECTION DE TENDANCES ÉMERGENTES
# ──────────────────────────────────────────────

def detect_trends(user_id):
    """
    Détecte les tendances émergentes en comparant les 7 derniers jours
    aux 7 jours précédents. Retourne hashtags, formats et métriques en hausse.
    """
    now = datetime.utcnow()
    week_ago = (now - timedelta(days=7)).strftime('%Y-%m-%d')
    two_weeks_ago = (now - timedelta(days=14)).strftime('%Y-%m-%d')

    with get_connection() as conn:
        # Vidéos semaine courante
        recent = _fetchall(conn, """
            SELECT description, views, likes, comments, shares, saves, platform,
                   duration, create_time
            FROM videos
            WHERE user_id = %s AND create_time >= %s
        """, (user_id, week_ago))

        # Vidéos semaine précédente
        previous = _fetchall(conn, """
            SELECT description, views, likes, comments, shares, saves, platform,
                   duration, create_time
            FROM videos
            WHERE user_id = %s AND create_time >= %s AND create_time < %s
        """, (user_id, two_weeks_ago, week_ago))

    # --- Hashtag trends ---
    def count_hashtags(videos_list):
        counter = Counter()
        for v in videos_list:
            for tag in extract_hashtags(v.get('description', '')):
                counter[tag] += 1
        return counter

    recent_tags = count_hashtags(recent)
    previous_tags = count_hashtags(previous)

    trending_hashtags = []
    for tag, count in recent_tags.most_common(50):
        prev_count = previous_tags.get(tag, 0)
        if prev_count == 0:
            growth = 100  # nouveau hashtag
            status = 'new'
        else:
            growth = round(((count - prev_count) / prev_count) * 100, 1)
            status = 'rising' if growth > 20 else ('stable' if growth >= -20 else 'declining')

        if status in ('new', 'rising'):
            trending_hashtags.append({
                'hashtag': f'#{tag}',
                'this_week': count,
                'last_week': prev_count,
                'growth_pct': growth,
                'status': status,
            })

    trending_hashtags.sort(key=lambda x: x['growth_pct'], reverse=True)

    # --- Format trends (durée) ---
    def avg_metric(vids, key):
        vals = [v.get(key, 0) or 0 for v in vids]
        return sum(vals) / max(1, len(vals))

    def bucket_duration(dur):
        dur = dur or 0
        if dur <= 15:
            return '0-15s'
        elif dur <= 30:
            return '15-30s'
        elif dur <= 60:
            return '30-60s'
        else:
            return '60s+'

    format_perf = {}
    for v in recent:
        bucket = bucket_duration(v.get('duration', 0))
        if bucket not in format_perf:
            format_perf[bucket] = {'views': [], 'engagement': []}
        format_perf[bucket]['views'].append(v.get('views', 0) or 0)
        eng = (v.get('likes', 0) or 0) + (v.get('comments', 0) or 0) + \
              (v.get('shares', 0) or 0) + (v.get('saves', 0) or 0)
        format_perf[bucket]['engagement'].append(eng)

    format_trends = []
    for bucket, data in format_perf.items():
        n = len(data['views'])
        avg_v = sum(data['views']) / max(1, n)
        avg_e = sum(data['engagement']) / max(1, n)
        format_trends.append({
            'format': bucket,
            'count': n,
            'avg_views': round(avg_v),
            'avg_engagement': round(avg_e),
            'engagement_rate': round((avg_e / max(1, avg_v)) * 100, 2),
        })
    format_trends.sort(key=lambda x: x['avg_views'], reverse=True)

    # --- Métriques globales week-over-week ---
    def sum_metric(vids, key):
        return sum(v.get(key, 0) or 0 for v in vids)

    metrics_wow = {}
    for key in ('views', 'likes', 'comments', 'shares', 'saves'):
        curr = sum_metric(recent, key)
        prev = sum_metric(previous, key)
        growth = round(((curr - prev) / max(1, prev)) * 100, 1)
        metrics_wow[key] = {
            'this_week': curr,
            'last_week': prev,
            'growth_pct': growth,
            'trend': 'up' if growth > 5 else ('down' if growth < -5 else 'stable'),
        }

    metrics_wow['posts'] = {
        'this_week': len(recent),
        'last_week': len(previous),
        'growth_pct': round(((len(recent) - len(previous)) / max(1, len(previous))) * 100, 1),
        'trend': 'up' if len(recent) > len(previous) else ('down' if len(recent) < len(previous) else 'stable'),
    }

    return {
        'trending_hashtags': trending_hashtags[:15],
        'format_performance': format_trends,
        'week_over_week': metrics_wow,
        'period': {
            'current': {'from': week_ago, 'to': now.strftime('%Y-%m-%d')},
            'previous': {'from': two_weeks_ago, 'to': week_ago},
        },
    }


# ──────────────────────────────────────────────
# 4. MÉTRIQUES DE CROISSANCE
# ──────────────────────────────────────────────

def get_growth_metrics(user_id, days=30):
    """
    Calcule les métriques de croissance par compte :
    - Croissance followers
    - Croissance engagement
    - Taux de publication
    - Meilleur jour de publication
    """
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime('%Y-%m-%d')

    with get_connection() as conn:
        snapshots = _fetchall(conn, """
            SELECT account_username, platform, snapshot_date,
                   followers, total_views, total_likes, total_comments,
                   total_shares, total_saves, total_videos, engagement_rate
            FROM daily_snapshots
            WHERE user_id = %s AND snapshot_date >= %s
            ORDER BY account_username, platform, snapshot_date ASC
        """, (user_id, cutoff))

    # Grouper par compte
    accounts = {}
    for s in snapshots:
        key = f"{s['account_username']}:{s['platform']}"
        if key not in accounts:
            accounts[key] = []
        accounts[key].append(s)

    results = []
    for key, snaps in accounts.items():
        if len(snaps) < 2:
            continue

        first = snaps[0]
        last = snaps[-1]

        # Croissance followers
        f_start = first.get('followers', 0) or 0
        f_end = last.get('followers', 0) or 0
        f_growth = f_end - f_start
        f_growth_pct = round((f_growth / max(1, f_start)) * 100, 1)

        # Croissance views
        v_start = first.get('total_views', 0) or 0
        v_end = last.get('total_views', 0) or 0
        v_growth = v_end - v_start

        # Engagement moyen sur la période
        eng_rates = [s.get('engagement_rate', 0) or 0 for s in snaps]
        avg_eng_rate = round(sum(eng_rates) / max(1, len(eng_rates)), 2)

        # Vidéos publiées
        vid_start = first.get('total_videos', 0) or 0
        vid_end = last.get('total_videos', 0) or 0
        new_videos = max(0, vid_end - vid_start)

        # Posting frequency
        period_days = max(1, (datetime.utcnow() - datetime.strptime(str(cutoff), '%Y-%m-%d')).days)
        posting_freq = round(new_videos / period_days * 7, 1)  # vidéos par semaine

        results.append({
            'account': first['account_username'],
            'platform': first['platform'],
            'followers_start': f_start,
            'followers_end': f_end,
            'followers_growth': f_growth,
            'followers_growth_pct': f_growth_pct,
            'views_growth': v_growth,
            'new_videos': new_videos,
            'posting_freq_per_week': posting_freq,
            'avg_engagement_rate': avg_eng_rate,
            'data_points': len(snaps),
        })

    results.sort(key=lambda x: x['followers_growth_pct'], reverse=True)
    return results


# ──────────────────────────────────────────────
# 5. CONTENUS PERFORMANTS — TOP & FLOP
# ──────────────────────────────────────────────

def get_top_content(user_id, days=30, limit=10):
    """
    Identifie les contenus les plus performants et les moins performants.
    Permet de comprendre ce qui marche et ce qui ne marche pas.
    """
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime('%Y-%m-%d')

    with get_connection() as conn:
        videos = _fetchall(conn, """
            SELECT v.video_id, v.account_username, v.description, v.create_time,
                   v.views, v.likes, v.comments, v.shares, v.saves,
                   v.thumbnail_url, v.platform, v.duration,
                   a.followers
            FROM videos v
            LEFT JOIN accounts a ON a.username = v.account_username
                AND a.user_id = v.user_id AND a.platform = v.platform
            WHERE v.user_id = %s AND v.create_time >= %s AND v.views > 0
            ORDER BY v.views DESC
        """, (user_id, cutoff))

    for v in videos:
        views = v.get('views', 0) or 0
        engagement = (v.get('likes', 0) or 0) + (v.get('comments', 0) or 0) + \
                     (v.get('shares', 0) or 0) + (v.get('saves', 0) or 0)
        v['engagement_rate'] = round((engagement / max(1, views)) * 100, 2)
        v['virality_score'] = compute_virality_score(v)
        v['hashtags'] = extract_hashtags(v.get('description', ''))

    top = sorted(videos, key=lambda x: x['virality_score'], reverse=True)[:limit]
    flop = sorted(videos, key=lambda x: x['virality_score'])[:limit]

    return {'top': top, 'flop': flop}


# ──────────────────────────────────────────────
# 6. INSIGHTS MARKETING AUTOMATIQUES
# ──────────────────────────────────────────────

def generate_insights(user_id):
    """
    Génère des insights marketing exploitables basés sur les données.
    Retourne une liste de recommandations priorisées.
    """
    insights = []

    # --- Insight 1 : Meilleurs hashtags ---
    hashtags = compute_hashtag_stats(user_id, days=30)
    if hashtags:
        top3 = [h['hashtag'] for h in hashtags[:3]]
        best = hashtags[0]
        insights.append({
            'type': 'hashtags',
            'priority': 'high',
            'title': 'Hashtags les plus performants',
            'message': f"Vos 3 meilleurs hashtags : {', '.join(top3)}. "
                       f"{best['hashtag']} génère en moyenne {best['avg_views']} vues "
                       f"avec un taux d'engagement de {best['engagement_rate']}%.",
            'data': hashtags[:5],
        })

    # --- Insight 2 : Tendances émergentes ---
    trends = detect_trends(user_id)
    rising = trends.get('trending_hashtags', [])
    if rising:
        new_tags = [t for t in rising if t['status'] == 'new']
        if new_tags:
            insights.append({
                'type': 'trends',
                'priority': 'high',
                'title': 'Nouveaux hashtags détectés',
                'message': f"{len(new_tags)} nouveau(x) hashtag(s) cette semaine : "
                           f"{', '.join(t['hashtag'] for t in new_tags[:5])}.",
                'data': new_tags[:5],
            })

    # --- Insight 3 : Format optimal ---
    formats = trends.get('format_performance', [])
    if formats:
        best_format = max(formats, key=lambda x: x['avg_views'])
        insights.append({
            'type': 'format',
            'priority': 'medium',
            'title': 'Format de vidéo optimal',
            'message': f"Les vidéos de {best_format['format']} performent le mieux "
                       f"avec {best_format['avg_views']} vues en moyenne "
                       f"et {best_format['engagement_rate']}% d'engagement.",
            'data': formats,
        })

    # --- Insight 4 : Croissance ---
    growth = get_growth_metrics(user_id, days=30)
    if growth:
        growing = [g for g in growth if g['followers_growth_pct'] > 0]
        declining = [g for g in growth if g['followers_growth_pct'] < 0]

        if growing:
            best = max(growing, key=lambda x: x['followers_growth_pct'])
            insights.append({
                'type': 'growth',
                'priority': 'medium',
                'title': 'Compte en forte croissance',
                'message': f"@{best['account']} ({best['platform']}) a gagné "
                           f"{best['followers_growth']} followers (+{best['followers_growth_pct']}%) "
                           f"sur les 30 derniers jours.",
                'data': best,
            })

        if declining:
            worst = min(declining, key=lambda x: x['followers_growth_pct'])
            insights.append({
                'type': 'alert',
                'priority': 'high',
                'title': 'Compte en baisse',
                'message': f"@{worst['account']} ({worst['platform']}) a perdu "
                           f"{abs(worst['followers_growth'])} followers ({worst['followers_growth_pct']}%).",
                'data': worst,
            })

    # --- Insight 5 : Week-over-week ---
    wow = trends.get('week_over_week', {})
    for metric in ('views', 'likes'):
        data = wow.get(metric)
        if data and data['trend'] == 'up' and data['growth_pct'] > 20:
            insights.append({
                'type': 'momentum',
                'priority': 'medium',
                'title': f"{metric.capitalize()} en forte hausse",
                'message': f"+{data['growth_pct']}% de {metric} cette semaine "
                           f"({data['this_week']:,} vs {data['last_week']:,} la semaine précédente).",
                'data': data,
            })
        elif data and data['trend'] == 'down' and data['growth_pct'] < -20:
            insights.append({
                'type': 'alert',
                'priority': 'high',
                'title': f"{metric.capitalize()} en baisse",
                'message': f"{data['growth_pct']}% de {metric} cette semaine.",
                'data': data,
            })

    # --- Insight 6 : Fréquence de publication ---
    if growth:
        avg_freq = sum(g['posting_freq_per_week'] for g in growth) / max(1, len(growth))
        if avg_freq < 2:
            insights.append({
                'type': 'recommendation',
                'priority': 'medium',
                'title': 'Fréquence de publication faible',
                'message': f"Vous publiez en moyenne {round(avg_freq, 1)} vidéos/semaine. "
                           f"Les algorithmes favorisent 3-5 publications/semaine minimum.",
            })

    # Tri par priorité
    priority_order = {'high': 0, 'medium': 1, 'low': 2}
    insights.sort(key=lambda x: priority_order.get(x.get('priority', 'low'), 2))

    return insights


# ──────────────────────────────────────────────
# 7. EXPORT PIPELINE
# ──────────────────────────────────────────────

def run_full_analysis(user_id):
    """
    Exécute le pipeline complet d'analyse pour un utilisateur.
    Retourne un rapport consolidé prêt à être consommé par l'API.
    """
    return {
        'generated_at': datetime.utcnow().isoformat(),
        'user_id': user_id,
        'insights': generate_insights(user_id),
        'trends': detect_trends(user_id),
        'hashtags': compute_hashtag_stats(user_id, days=30)[:20],
        'viral_content': get_viral_videos(user_id, limit=10, days=30),
        'growth': get_growth_metrics(user_id, days=30),
    }
