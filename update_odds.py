# ============================================================
# update_odds.py
# GitHub Actionsから実行するオッズ自動更新スクリプト
# predictions_YYYYMMDD.jsonのオッズ/EV部分だけ更新する
# ============================================================

import json, re, time, requests, os, sys
from datetime import datetime

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept-Encoding': 'gzip, deflate', 'Accept': '*/*',
    'Referer': 'https://race.netkeiba.com/'
}

NKB_PLACE = {
    '札幌':'01','函館':'02','福島':'03','新潟':'04','東京':'05',
    '中山':'06','中京':'07','京都':'08','阪神':'09','小倉':'10'
}

def get_nk_race_ids(date_str):
    url = f"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={date_str}"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.encoding = 'euc-jp'
    return list(dict.fromkeys(re.findall(r'race_id=(\d{12})', resp.text)))

def build_race_map(races, nk_ids):
    mapping = {}
    for r in races:
        pcode = NKB_PLACE.get(r['place'])
        if not pcode: continue
        rno = str(int(r['race_no'])).zfill(2)
        for nkid in nk_ids:
            if nkid[4:6] == pcode and nkid[10:12] == rno:
                mapping[r['race_id']] = nkid
                break
    return mapping

def fetch_odds(nk_race_id):
    """netkeibaから単勝オッズを取得"""
    url = f"https://race.netkeiba.com/api/api_get_jra_odds.html?race_id={nk_race_id}&type=1&action=update"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return {}
        # zlib圧縮の場合
        try:
            import zlib
            data = json.loads(zlib.decompress(resp.content, 16 + zlib.MAX_WBITS))
        except:
            data = resp.json()

        odds_map = {}
        for item in data.get('data', {}).get('odds', {}).get('1', []):
            try:
                umaban = int(item[0])
                odds   = float(item[1])
                odds_map[umaban] = odds
            except:
                pass
        return odds_map
    except Exception as e:
        print(f"      オッズ取得失敗 {nk_race_id}: {e}")
        return {}

def update_predictions_file(filepath):
    """predictions_YYYYMMDD.jsonのオッズとEVを更新"""
    with open(filepath, encoding='utf-8') as f:
        data = json.load(f)

    date_str = data['date']
    print(f"  日付: {date_str} / {len(data['races'])}レース")

    nk_ids = get_nk_race_ids(date_str)
    race_map = build_race_map(data['races'], nk_ids)
    print(f"  マッチング: {len(race_map)}/{len(data['races'])}レース")

    updated_count = 0
    for r in data['races']:
        nk_id = race_map.get(r['race_id'])
        if not nk_id:
            continue

        odds_map = fetch_odds(nk_id)
        if not odds_map:
            continue

        # 各馬のオッズとEVを更新
        for h in r.get('horses', []):
            um = h.get('umaban')
            if um in odds_map:
                new_odds = odds_map[um]
                h['tansho_odds'] = new_odds
                # EV再計算（単勝EV = p_ability × odds / 100）
                p_ab = h.get('p_ability', 0) or 0
                if p_ab > 0 and new_odds > 0:
                    h['ev_tansho'] = round(p_ab / 100 * new_odds, 3)
                    h['ev_tansho_anomaly'] = new_odds > 50  # 50倍超は異常値フラグ

                # divergence再計算（AIの単勝確率と市場確率の乖離）
                market_prob = 1 / new_odds if new_odds > 0 else 0
                h['divergence'] = round((p_ab / 100) - market_prob, 3)

                # myomi_score再計算
                div = h.get('divergence', 0)
                h['myomi_score'] = round(max(div, 0) * new_odds / 50, 3) if new_odds <= 50 else 0.0

        updated_count += 1
        time.sleep(0.3)

    print(f"  更新: {updated_count}レース")

    # 生成時刻を更新
    data['generated_at'] = datetime.now().isoformat()
    data['odds_updated_at'] = datetime.now().isoformat()

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return True

# ── メイン ────────────────────────────────────────────────
if __name__ == '__main__':
    # manifest.jsonから対象ファイルを取得
    manifest_path = 'manifest.json'
    if not os.path.exists(manifest_path):
        print("manifest.json が見つかりません")
        sys.exit(1)

    with open(manifest_path) as f:
        manifest = json.load(f)

    dates = manifest.get('dates', [])
    if not dates:
        print("manifest.jsonに日付がありません")
        sys.exit(0)

    print(f"対象日付: {dates}")

    for date_str in dates:
        filepath = f"predictions_{date_str}.json"
        if not os.path.exists(filepath):
            print(f"  {filepath} が見つかりません、スキップ")
            continue

        print(f"\n>> {filepath} を更新中...")
        try:
            update_predictions_file(filepath)
            print(f"  ✅ 完了")
        except Exception as e:
            print(f"  ❌ エラー: {e}")

    print("\n全処理完了")
