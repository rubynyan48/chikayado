"""大学入試センターの「試験場一覧」のPDF（pdftotext -layout で文字にしたもの）から、試験場の名前・住所・道順・志願者数を取り出す（11/24〜）。

使い方: pdftotext -layout 一覧.pdf 一覧.txt && python parse_exam_pdf.py 一覧.txt ../config/kyotsu_sites.json
取り出した一覧から選んで config/exams/ に試験場を足す。
"""
import sys
import re, json, unicodedata
lines = open(sys.argv[1], encoding='utf-8').read().split('\n')
CODE = re.compile(r'[０-９]{6}')
TEL = re.compile(r'\s(\d{2,5}-\d{1,4}-\d{3,4})\s*$')
z = lambda s: unicodedata.normalize('NFKC', s)
rows = []; pref = univ = None
def segs(c):
    return [(mm.start(), mm.group()) for mm in re.finditer(r'\S+(?: \S+)*', c)]
i = 0
while i < len(lines):
    ln = lines[i]
    m = CODE.search(ln)
    if m and re.search(r'\d', ln[m.end():m.end()+30]):
        head = ln[:m.start()]
        hs = segs(head)
        name_col, name = hs[-1] if hs else (24, '')
        others = [t for p, t in hs[:-1]]
        if len(others) >= 2: pref, univ = others[0], others[1]
        elif len(others) == 1:
            if hs[0][0] < 6: pref, univ = others[0], None
            else: univ = others[0]
        rest = ln[m.end():]
        am = re.match(r'\s+([\d,]+)\s+(.*)$', rest)
        applicants = int(am.group(1).replace(',', ''))
        route = am.group(2)
        tm = TEL.search(route); tel = tm.group(1) if tm else ''
        if tm: route = route[:tm.start()]
        # 前の行: 住所（いちばん右）と、名前の前半
        j = i - 1; pre = []
        while j >= 0 and lines[j].strip():
            pre.insert(0, lines[j]); j -= 1
        address = ''
        for c in pre:
            for p, t in segs(c):
                if p >= 55: address = t; name = hs[-1][1] if hs else ''
                elif abs(p - name_col) <= 3: name = t + name
                elif univ and p < name_col - 3: univ = univ if t in univ else t + univ
        k = i + 1
        while k < len(lines) and lines[k].strip() and not CODE.search(lines[k]):
            for p, t in segs(lines[k]):
                if t.startswith('計'): continue
                if abs(p - name_col) <= 3: name += t
                elif p < name_col - 3: univ = (univ or '') + t
                else: route += t
            k += 1
        rows.append(dict(pref=z(pref or ''), univ=z(univ or ''), name=z(name), code=z(m.group()), applicants=applicants,
                         address=z(address), route=z(re.sub(r'\s+', '', route)), tel=tel))
        i = k
        continue
    i += 1

# 県とまとめ直し
PREFS = '北海道 青森県 岩手県 宮城県 秋田県 山形県 福島県 茨城県 栃木県 群馬県 埼玉県 千葉県 東京都 神奈川県 新潟県 富山県 石川県 福井県 山梨県 長野県 岐阜県 静岡県 愛知県 三重県 滋賀県 京都府 大阪府 兵庫県 奈良県 和歌山県 鳥取県 島根県 岡山県 広島県 山口県 徳島県 香川県 愛媛県 高知県 福岡県 佐賀県 長崎県 熊本県 大分県 宮崎県 鹿児島県 沖縄県'.split()
cur = None; cu = None
for r in rows:
    p = r['pref']
    if ' ' in p: p, u = p.split(' ', 1); r['univ'] = r['univ'] or u
    if p in PREFS: cur = p
    elif p: r['univ'] = p
    r['pref'] = cur
    if r['univ']: cu = r['univ']
    r['univ'] = r['univ'] or cu
    g = re.search(r'(開門予定時刻|開門時刻)?(\d{1,2})(?::(\d{2})|時(\d{2})?分?)(開門|開場)?', r['route'])
    r['gate'] = (f"{int(g.group(2))}:{g.group(3) or g.group(4) or '00'}") if g and (g.group(1) or g.group(5)) else ''
    r['hp_note'] = bool(re.search(r'(HP|ホームページ).*(確認|参照)', r['route']))
    r['route'] = r['route'].strip('、。 ')
json.dump(rows, open(sys.argv[2], 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(f'{len(rows)}か所')
