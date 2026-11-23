"""Render docs/tech.html: deeply illustrated technical architecture guide + ~15-min Neon-san dialogue player."""

from __future__ import annotations

import html
from string import Template
from typing import Any

TECH_CSS = """
.tech-hero {
  padding: 0.95rem 1.05rem;
  border-left: 4px solid #0891b2;
  background: linear-gradient(135deg, #ecfeff 0%, #ffffff 65%);
}
.tech-hero-badge {
  display: inline-block;
  font-size: 0.74rem;
  font-weight: 800;
  padding: 0.16rem 0.62rem;
  border-radius: 999px;
  background: #0891b2;
  color: #ffffff;
  margin-bottom: 0.35rem;
}
.tech-hero h2 {
  margin: 0.1rem 0 0.35rem;
  font-size: clamp(1.06rem, 4vw, 1.38rem);
  color: #164e63;
  line-height: 1.35;
}
.tech-hero p {
  margin: 0;
  font-size: 0.86rem;
  color: var(--ink);
  line-height: 1.65;
}
.toc-card {
  padding: 0.78rem 0.95rem;
}
.toc-title {
  font-size: 0.78rem;
  font-weight: 700;
  color: var(--muted);
  margin: 0 0 0.45rem;
}
.toc-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.36rem;
}
.toc-pill {
  text-decoration: none;
  font-size: 0.78rem;
  font-weight: 700;
  padding: 0.3rem 0.65rem;
  border-radius: 999px;
  background: #fff;
  border: 1px solid var(--border);
  color: var(--forest-dark);
}
.toc-pill:hover {
  background: var(--forest-soft);
  border-color: var(--forest);
}
.speaker-neon {
  background: #ecfeff;
  color: #0e7490;
}
.tech-chapter {
  scroll-margin-top: 1rem;
}
.tech-body {
  padding: 0.95rem 1.05rem 1.15rem;
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
  font-size: 0.92rem;
  line-height: 1.75;
}
.tech-body h3 {
  margin: 0.25rem 0 0.1rem;
  font-size: 1rem;
  color: var(--forest-dark);
  border-bottom: 2px solid var(--forest-soft);
  padding-bottom: 0.2rem;
}
.tech-body p {
  margin: 0;
}
.tech-body ul {
  margin: 0.1rem 0;
  padding-left: 1.25rem;
}
.tech-body li {
  margin-bottom: 0.3rem;
}
.beginner-box {
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-left: 4px solid var(--amber);
  border-radius: 10px;
  padding: 0.72rem 0.9rem;
  font-size: 0.86rem;
  line-height: 1.68;
}
.beginner-box strong {
  color: #92400e;
  display: block;
  margin-bottom: 0.2rem;
}
.tech-spec-box {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-left: 4px solid #0891b2;
  border-radius: 10px;
  padding: 0.72rem 0.9rem;
  font-size: 0.85rem;
  line-height: 1.65;
}
.tech-spec-box strong {
  color: #0e7490;
}
.diagram-figure {
  margin: 0.2rem 0;
  background: #ffffff;
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 0.65rem;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}
.diagram-figure svg {
  width: 100%;
  height: auto;
  display: block;
}
.diagram-caption {
  margin-top: 0.45rem;
  font-size: 0.78rem;
  color: var(--muted);
  text-align: center;
  font-weight: 600;
}
.code-sample {
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 10px;
  padding: 0.8rem 0.95rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.78rem;
  line-height: 1.6;
  overflow-x: auto;
  white-space: pre;
}
.code-comment { color: #7dd3fc; }
.tech-table-wrap {
  width: 100%;
  overflow-x: auto;
  border: 1px solid var(--border);
  border-radius: 10px;
}
.tech-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82rem;
  min-width: 540px;
}
.tech-table th, .tech-table td {
  padding: 0.55rem 0.72rem;
  border-bottom: 1px solid var(--border);
  text-align: left;
  vertical-align: top;
}
.tech-table th {
  background: #f3f5f2;
  color: var(--forest-dark);
  font-weight: 800;
}
.tech-table tr:last-child td { border-bottom: none; }
.tech-grid-2 {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.75rem;
}
.tech-mini-card {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 0.72rem 0.85rem;
  background: #fcfcfa;
  font-size: 0.84rem;
}
.tech-mini-card h4 {
  margin: 0 0 0.25rem;
  font-size: 0.9rem;
  color: var(--forest-dark);
}
.tech-player-wrap {
  border-top: 4px solid #0891b2;
}
.tech-transcript-wrap {
  max-height: 52vh;
  overflow-y: auto;
  padding: 0.8rem 0.95rem 1.2rem;
}
@media (max-width: 720px) {
  .tech-grid-2 {
    grid-template-columns: minmax(0, 1fr);
  }
  .tech-transcript-wrap {
    max-height: 58vh;
  }
}
"""

SVG_DIAGRAM_1 = """
<svg viewBox="0 0 860 300" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="全自動ラジオ制作パイプライン全体図">
  <defs>
    <marker id="arr1" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 1 L 10 5 L 0 9 z" fill="#475569"/>
    </marker>
    <linearGradient id="bg1" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#f8fafc"/>
      <stop offset="100%" stop-color="#ecfeff"/>
    </linearGradient>
  </defs>
  <rect width="860" height="300" rx="14" fill="url(#bg1)"/>
  <text x="430" y="28" text-anchor="middle" font-family="sans-serif" font-size="15" font-weight="800" fill="#0f172a">毎朝7時までに自動で番組が届く 5ステップ・パイプライン全体図</text>

  <!-- Step 0: Cron -->
  <rect x="20" y="54" width="128" height="175" rx="10" fill="#ffffff" stroke="#64748b" stroke-width="2"/>
  <rect x="20" y="54" width="128" height="30" rx="10" fill="#334155"/>
  <text x="84" y="74" text-anchor="middle" font-family="sans-serif" font-size="12" font-weight="700" fill="#ffffff">自動起動 (CI)</text>
  <text x="84" y="108" text-anchor="middle" font-family="sans-serif" font-size="12" font-weight="700" fill="#0f172a">GitHub Actions</text>
  <text x="84" y="128" text-anchor="middle" font-family="sans-serif" font-size="11" fill="#475569">05:17 JST メイン</text>
  <text x="84" y="145" text-anchor="middle" font-family="sans-serif" font-size="11" fill="#475569">06:13 JST 予備</text>
  <rect x="30" y="162" width="108" height="52" rx="6" fill="#f1f5f9"/>
  <text x="84" y="180" text-anchor="middle" font-family="sans-serif" font-size="10" font-weight="700" fill="#334155">GitHub Secrets</text>
  <text x="84" y="196" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#475569">APIキーを安全注入</text>

  <line x1="148" y1="140" x2="174" y2="140" stroke="#475569" stroke-width="2" marker-end="url(#arr1)"/>

  <!-- Step 1: Collect -->
  <rect x="178" y="54" width="144" height="175" rx="10" fill="#ffffff" stroke="#0284c7" stroke-width="2"/>
  <rect x="178" y="54" width="144" height="30" rx="10" fill="#0284c7"/>
  <text x="250" y="74" text-anchor="middle" font-family="sans-serif" font-size="12" font-weight="700" fill="#ffffff">1. 材料集め</text>
  <text x="250" y="106" text-anchor="middle" font-family="sans-serif" font-size="11" font-weight="700" fill="#0369a1">Open-Meteo (気象)</text>
  <text x="250" y="124" text-anchor="middle" font-family="sans-serif" font-size="11" font-weight="700" fill="#0369a1">P2PQuake v2 (地震)</text>
  <text x="250" y="142" text-anchor="middle" font-family="sans-serif" font-size="11" fill="#334155">jpholiday (祝日15分)</text>
  <rect x="188" y="156" width="124" height="60" rx="6" fill="#f0f9ff"/>
  <text x="250" y="174" text-anchor="middle" font-family="sans-serif" font-size="10" font-weight="700" fill="#0369a1">設定＆記憶データ</text>
  <text x="250" y="190" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#475569">28日/90日重複防止</text>
  <text x="250" y="205" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#475569">事前編成カレンダー</text>

  <line x1="322" y1="140" x2="348" y2="140" stroke="#475569" stroke-width="2" marker-end="url(#arr1)"/>

  <!-- Step 2: 3-Phase AI -->
  <rect x="352" y="54" width="160" height="175" rx="10" fill="#ffffff" stroke="#7c3aed" stroke-width="2"/>
  <rect x="352" y="54" width="160" height="30" rx="10" fill="#7c3aed"/>
  <text x="432" y="74" text-anchor="middle" font-family="sans-serif" font-size="12" font-weight="700" fill="#ffffff">2. AI制作＆校閲</text>
  <rect x="362" y="93" width="140" height="36" rx="6" fill="#f5f3ff"/>
  <text x="432" y="109" text-anchor="middle" font-family="sans-serif" font-size="10" font-weight="700" fill="#5b21b6">Phase A: Hydrogen + 検索</text>
  <text x="432" y="123" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#475569">最新小平＆防災ニュース調査</text>
  <rect x="362" y="135" width="140" height="36" rx="6" fill="#ecfeff"/>
  <text x="432" y="151" text-anchor="middle" font-family="sans-serif" font-size="10" font-weight="700" fill="#0e7490">Phase B: Gemini 4 Neon</text>
  <text x="432" y="165" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#475569">掛け合いJSON台本を執筆</text>
  <rect x="362" y="177" width="140" height="42" rx="6" fill="#fef3c7"/>
  <text x="432" y="193" text-anchor="middle" font-family="sans-serif" font-size="10" font-weight="700" fill="#92400e">Phase C: Hydrogen 校閲</text>
  <text x="432" y="208" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#78350f">年号・数値の裏取り修正</text>

  <line x1="512" y1="140" x2="538" y2="140" stroke="#475569" stroke-width="2" marker-end="url(#arr1)"/>

  <!-- Step 3: Audio DSP -->
  <rect x="542" y="54" width="146" height="175" rx="10" fill="#ffffff" stroke="#d97706" stroke-width="2"/>
  <rect x="542" y="54" width="146" height="30" rx="10" fill="#d97706"/>
  <text x="615" y="74" text-anchor="middle" font-family="sans-serif" font-size="12" font-weight="700" fill="#ffffff">3. 音声＆音響DSP</text>
  <text x="615" y="106" text-anchor="middle" font-family="sans-serif" font-size="11" font-weight="700" fill="#92400e">Gemini 3.8 Flash TTS</text>
  <text x="615" y="122" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#475569">感情タグ・マルチ話者合成</text>
  <text x="615" y="146" text-anchor="middle" font-family="sans-serif" font-size="11" font-weight="700" fill="#92400e">NumPy 数式BGM</text>
  <text x="615" y="162" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#475569">サイン波・リバーブ自前生成</text>
  <rect x="552" y="174" width="126" height="44" rx="6" fill="#fffbeb"/>
  <text x="615" y="191" text-anchor="middle" font-family="sans-serif" font-size="10" font-weight="700" fill="#b45309">先読みダッキング＆FFmpeg</text>
  <text x="615" y="206" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#475569">-16 LUFS MP3 + タイムライン</text>

  <line x1="688" y1="140" x2="714" y2="140" stroke="#475569" stroke-width="2" marker-end="url(#arr1)"/>

  <!-- Step 4: Static Portal -->
  <rect x="718" y="54" width="124" height="175" rx="10" fill="#ffffff" stroke="#1b5e3c" stroke-width="2"/>
  <rect x="718" y="54" width="124" height="30" rx="10" fill="#1b5e3c"/>
  <text x="780" y="74" text-anchor="middle" font-family="sans-serif" font-size="12" font-weight="700" fill="#ffffff">4. 公開ポータル</text>
  <text x="780" y="106" text-anchor="middle" font-family="sans-serif" font-size="11" font-weight="700" fill="#124028">build_site.py</text>
  <text x="780" y="124" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#475569">docs/ 静的HTML生成</text>
  <text x="780" y="146" text-anchor="middle" font-family="sans-serif" font-size="11" font-weight="700" fill="#124028">GitHub Pages</text>
  <text x="780" y="164" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#475569">毎朝07:00前に公開</text>
  <rect x="728" y="176" width="104" height="42" rx="6" fill="#e7f4ec"/>
  <text x="780" y="194" text-anchor="middle" font-family="sans-serif" font-size="10" font-weight="700" fill="#1b5e3c">スマホ＆PC再生</text>
  <text x="780" y="209" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#124028">同期字幕・シーク対応</text>

  <!-- Feedback Loop Bottom -->
  <path d="M 780 232 L 780 264 L 250 264 L 250 234" fill="none" stroke="#0891b2" stroke-width="2" stroke-dasharray="5,4" marker-end="url(#arr1)"/>
  <rect x="338" y="248" width="356" height="28" rx="14" fill="#ecfeff" stroke="#0891b2" stroke-width="1.5"/>
  <text x="516" y="266" text-anchor="middle" font-family="sans-serif" font-size="11" font-weight="700" fill="#0e7490">翌日の放送へ記憶を蓄積（knowledge_log.json / topic_history.json）</text>
</svg>
"""

SVG_DIAGRAM_2 = """
<svg viewBox="0 0 860 320" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="設定ファイル・ライブAPI・重複防止メモリ連携図">
  <defs>
    <marker id="arr2" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 1 L 10 5 L 0 9 z" fill="#1b5e3c"/>
    </marker>
  </defs>
  <rect width="860" height="320" rx="14" fill="#f8fafc"/>
  <text x="430" y="28" text-anchor="middle" font-family="sans-serif" font-size="15" font-weight="800" fill="#0f172a">図解②：台本を作る前に集める「リアルタイム情報・カレンダー・長期記憶」</text>

  <!-- Left: Live APIs & jpholiday -->
  <rect x="24" y="48" width="248" height="248" rx="12" fill="#ffffff" stroke="#0284c7" stroke-width="2"/>
  <rect x="24" y="48" width="248" height="30" rx="12" fill="#0284c7"/>
  <text x="148" y="68" text-anchor="middle" font-family="sans-serif" font-size="12" font-weight="700" fill="#ffffff">外部ライブデータ ＆ 祝日判定</text>
  <rect x="36" y="88" width="224" height="58" rx="8" fill="#f0f9ff" stroke="#bae6fd"/>
  <text x="46" y="106" font-family="sans-serif" font-size="11" font-weight="700" fill="#0369a1">Open-Meteo API（天気）</text>
  <text x="46" y="122" font-family="sans-serif" font-size="10" fill="#334155">小平市座標 (35.7285, 139.4775)</text>
  <text x="46" y="136" font-family="sans-serif" font-size="10" fill="#334155">気温・湿度・乾燥/寒暖差注意を算出</text>

  <rect x="36" y="156" width="224" height="64" rx="8" fill="#fef2f2" stroke="#fecaca"/>
  <text x="46" y="174" font-family="sans-serif" font-size="11" font-weight="700" fill="#b91c1c">P2PQuake API v2（地震）</text>
  <text x="46" y="190" font-family="sans-serif" font-size="10" fill="#334155">48時間以内の地震履歴 (codes=551)</text>
  <text x="46" y="204" font-family="sans-serif" font-size="10" fill="#991b1b">関東震度4+/全国5弱+ → 緊急特集(+4分)</text>

  <rect x="36" y="230" width="224" height="54" rx="8" fill="#fffbeb" stroke="#fde68a"/>
  <text x="46" y="248" font-family="sans-serif" font-size="11" font-weight="700" fill="#b45309">jpholiday ＆ special_days.json</text>
  <text x="46" y="264" font-family="sans-serif" font-size="10" fill="#334155">土日祝を自動判定し15分拡大版へ切替</text>
  <text x="46" y="278" font-family="sans-serif" font-size="10" fill="#334155">防災記念日カウントダウン・前日予告生成</text>

  <!-- Center: Resolver Engine -->
  <rect x="318" y="96" width="224" height="156" rx="14" fill="#ffffff" stroke="#1b5e3c" stroke-width="2.5"/>
  <rect x="318" y="96" width="224" height="32" rx="14" fill="#1b5e3c"/>
  <text x="430" y="117" text-anchor="middle" font-family="sans-serif" font-size="12" font-weight="700" fill="#ffffff">番組編成・重複ガード司令塔</text>
  <text x="430" y="148" text-anchor="middle" font-family="sans-serif" font-size="11" font-weight="700" fill="#124028">schedule_calendar.py</text>
  <text x="430" y="165" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#475569">resolve_day_plan() で放送尺・文字数決定</text>
  <line x1="336" y1="178" x2="524" y2="178" stroke="#e2e8f0" stroke-width="1.5"/>
  <text x="430" y="198" text-anchor="middle" font-family="sans-serif" font-size="11" font-weight="700" fill="#124028">build_dedup_context()</text>
  <text x="430" y="215" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#475569">小平ネタ: 28日間重複禁止</text>
  <text x="430" y="231" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#475569">専門家用語: 90日間重複禁止</text>

  <line x1="272" y1="172" x2="314" y2="172" stroke="#1b5e3c" stroke-width="2" marker-end="url(#arr2)"/>

  <!-- Right: Config & Memory JSONs -->
  <rect x="588" y="48" width="248" height="248" rx="12" fill="#ffffff" stroke="#7c3aed" stroke-width="2"/>
  <rect x="588" y="48" width="248" height="30" rx="12" fill="#7c3aed"/>
  <text x="712" y="68" text-anchor="middle" font-family="sans-serif" font-size="12" font-weight="700" fill="#ffffff">番組設定・カレンダー・長期記憶 JSON</text>

  <rect x="600" y="88" width="224" height="58" rx="8" fill="#f5f3ff" stroke="#ddd6fe"/>
  <text x="610" y="106" font-family="sans-serif" font-size="11" font-weight="700" fill="#5b21b6">program_schedule.json (事前予定)</text>
  <text x="610" y="122" font-family="sans-serif" font-size="10" fill="#334155">1か月超先の専門家テーマ＆リクエスト</text>
  <text x="610" y="136" font-family="sans-serif" font-size="10" fill="#334155">locked=true なら編集長AIも上書きしない</text>

  <rect x="600" y="156" width="224" height="58" rx="8" fill="#ecfeff" stroke="#a5f3fc"/>
  <text x="610" y="174" font-family="sans-serif" font-size="11" font-weight="700" fill="#0e7490">editorial_plan.json (編集長AI)</text>
  <text x="610" y="190" font-family="sans-serif" font-size="10" fill="#334155">毎週日曜に2週間先のリサーチ結果から</text>
  <text x="610" y="204" font-family="sans-serif" font-size="10" fill="#334155">週間テーマ軸＆ワクワク特集を策定</text>

  <rect x="600" y="224" width="224" height="60" rx="8" fill="#f0fdf4" stroke="#bbf7d0"/>
  <text x="610" y="242" font-family="sans-serif" font-size="11" font-weight="700" fill="#166534">topic_history / knowledge_log</text>
  <text x="610" y="258" font-family="sans-serif" font-size="10" fill="#334155">放送済みネタの90日履歴と小春の成長記録</text>
  <text x="610" y="272" font-family="sans-serif" font-size="10" fill="#334155">「前回学んだあの言葉！」の自然な振返り</text>

  <line x1="588" y1="172" x2="546" y2="172" stroke="#1b5e3c" stroke-width="2" marker-end="url(#arr2)"/>
</svg>
"""

SVG_DIAGRAM_3 = """
<svg viewBox="0 0 860 280" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="3フェーズハイブリッドAI制作＆自動校閲フロー">
  <defs>
    <marker id="arr3" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 1 L 10 5 L 0 9 z" fill="#475569"/>
    </marker>
  </defs>
  <rect width="860" height="280" rx="14" fill="#f8fafc"/>
  <text x="430" y="28" text-anchor="middle" font-family="sans-serif" font-size="15" font-weight="800" fill="#0f172a">図解③：役割分担で精度と面白さを両立する「3段階ハイブリッドAI制作」</text>

  <!-- Phase A -->
  <rect x="24" y="48" width="250" height="208" rx="12" fill="#ffffff" stroke="#0284c7" stroke-width="2"/>
  <rect x="24" y="48" width="250" height="32" rx="12" fill="#0284c7"/>
  <text x="149" y="69" text-anchor="middle" font-family="sans-serif" font-size="12" font-weight="700" fill="#ffffff">Phase A：最新調査（リサーチャー）</text>
  <text x="149" y="102" text-anchor="middle" font-family="sans-serif" font-size="12" font-weight="800" fill="#0369a1">gemini-4-hydrogen</text>
  <text x="149" y="120" text-anchor="middle" font-family="sans-serif" font-size="11" fill="#334155">+ Google Search Grounding</text>
  <rect x="38" y="134" width="222" height="106" rx="8" fill="#f0f9ff"/>
  <text x="48" y="154" font-family="sans-serif" font-size="10" fill="#1e293b">• 小平市公式・地域の季節話題を検索</text>
  <text x="48" y="172" font-family="sans-serif" font-size="10" fill="#1e293b">• 開催年（今年の日程か）を厳密確認</text>
  <text x="48" y="190" font-family="sans-serif" font-size="10" fill="#1e293b">• 参照した実在URLをリンク候補に抽出</text>
  <text x="48" y="208" font-family="sans-serif" font-size="10" font-weight="700" fill="#b45309">• 重大災害時は BREAKING_SPECIAL</text>
  <text x="58" y="224" font-family="sans-serif" font-size="10" font-weight="700" fill="#b45309">JSON で拡大特集を自動発動</text>

  <line x1="274" y1="150" x2="300" y2="150" stroke="#475569" stroke-width="2" marker-end="url(#arr3)"/>

  <!-- Phase B -->
  <rect x="304" y="48" width="252" height="208" rx="12" fill="#ffffff" stroke="#0891b2" stroke-width="2"/>
  <rect x="304" y="48" width="252" height="32" rx="12" fill="#0891b2"/>
  <text x="430" y="69" text-anchor="middle" font-family="sans-serif" font-size="12" font-weight="700" fill="#ffffff">Phase B：構成・執筆（構成作家）</text>
  <text x="430" y="102" text-anchor="middle" font-family="sans-serif" font-size="12" font-weight="800" fill="#0e7490">gemini-4-neon</text>
  <text x="430" y="120" text-anchor="middle" font-family="sans-serif" font-size="11" fill="#334155">JSON構造化出力 (application/json)</text>
  <rect x="318" y="134" width="224" height="106" rx="8" fill="#ecfeff"/>
  <text x="328" y="154" font-family="sans-serif" font-size="10" fill="#1e293b">• 小春・平蔵・専門家の自然な掛け合い</text>
  <text x="328" y="172" font-family="sans-serif" font-size="10" fill="#1e293b">• 表示用 text と読み上げ用 tts_text 分離</text>
  <text x="328" y="190" font-family="sans-serif" font-size="10" fill="#1e293b">• 地名かな開き ＆ &lt;laugh&gt; タグ付与</text>
  <text x="328" y="208" font-family="sans-serif" font-size="10" fill="#1e293b">• 5〜6コーナー・規定文字数 (3200/4800)</text>
  <text x="328" y="226" font-family="sans-serif" font-size="10" fill="#1e293b">• 防災ノート・連絡先・リンクも同時生成</text>

  <line x1="556" y1="150" x2="582" y2="150" stroke="#475569" stroke-width="2" marker-end="url(#arr3)"/>

  <!-- Phase C -->
  <rect x="586" y="48" width="250" height="208" rx="12" fill="#ffffff" stroke="#d97706" stroke-width="2"/>
  <rect x="586" y="48" width="250" height="32" rx="12" fill="#d97706"/>
  <text x="711" y="69" text-anchor="middle" font-family="sans-serif" font-size="12" font-weight="700" fill="#ffffff">Phase C：校閲ゲート（編集デスク）</text>
  <text x="711" y="102" text-anchor="middle" font-family="sans-serif" font-size="12" font-weight="800" fill="#b45309">gemini-4-hydrogen</text>
  <text x="711" y="120" text-anchor="middle" font-family="sans-serif" font-size="11" fill="#334155">+ Google Search 再監査</text>
  <rect x="600" y="134" width="222" height="106" rx="8" fill="#fffbeb"/>
  <text x="610" y="154" font-family="sans-serif" font-size="10" fill="#1e293b">• 全セリフの施設開館・日程・数値を再検索</text>
  <text x="610" y="172" font-family="sans-serif" font-size="10" fill="#1e293b">• 前年の日付混同などを即検出</text>
  <text x="610" y="190" font-family="sans-serif" font-size="10" fill="#1e293b">• 小春のボケは直後に訂正があれば許容</text>
  <text x="610" y="208" font-family="sans-serif" font-size="10" font-weight="700" fill="#92400e">• 問題行だけ FACT_CHECK_JSON で</text>
  <text x="620" y="224" font-family="sans-serif" font-size="10" font-weight="700" fill="#92400e">ピンポイント外科パッチ → 保存</text>
</svg>
"""

SVG_DIAGRAM_4 = """
<svg viewBox="0 0 860 320" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="3トラック音響合成と先読みダッキング・-16 LUFSマスタリング回路図">
  <defs>
    <marker id="arr4" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 1 L 10 5 L 0 9 z" fill="#334155"/>
    </marker>
  </defs>
  <rect width="860" height="320" rx="14" fill="#f8fafc"/>
  <text x="430" y="28" text-anchor="middle" font-family="sans-serif" font-size="15" font-weight="800" fill="#0f172a">図解④：スタジオ級「3トラック合成 ＆ 0.16秒先読みダッキング・-16 LUFS マスタリング」</text>

  <!-- Track 1: Speech -->
  <rect x="24" y="48" width="276" height="72" rx="10" fill="#fff1f2" stroke="#e11d48" stroke-width="1.8"/>
  <text x="38" y="70" font-family="sans-serif" font-size="12" font-weight="800" fill="#be123c">トラック1：会話音声 (Speech)</text>
  <text x="38" y="89" font-family="sans-serif" font-size="10" fill="#334155">Gemini 3.8 Flash TTS (SHA-256キャッシュ)</text>
  <text x="38" y="105" font-family="sans-serif" font-size="10" fill="#334155">44.1kHz化・RMS -20dBFS均一化・左右パンニング</text>

  <!-- Track 2: BGM -->
  <rect x="24" y="134" width="276" height="72" rx="10" fill="#eff6ff" stroke="#2563eb" stroke-width="1.8"/>
  <text x="38" y="156" font-family="sans-serif" font-size="12" font-weight="800" fill="#1d4ed8">トラック2：BGMベッド (bgm_synth.py)</text>
  <text x="38" y="175" font-family="sans-serif" font-size="10" fill="#334155">NumPy数式でエレキピアノ・パッド・ベース生成</text>
  <text x="38" y="191" font-family="sans-serif" font-size="10" fill="#334155">4,200Hz ローパスで声の帯域をスッキリ空ける</text>

  <!-- Track 3: Jingles -->
  <rect x="24" y="220" width="276" height="72" rx="10" fill="#fef3c7" stroke="#d97706" stroke-width="1.8"/>
  <text x="38" y="242" font-family="sans-serif" font-size="12" font-weight="800" fill="#b45309">トラック3：ジングル (4種)</text>
  <text x="38" y="261" font-family="sans-serif" font-size="10" fill="#334155">OP / Stinger / ゲスト登場 / ED テーマ</text>
  <text x="38" y="277" font-family="sans-serif" font-size="10" fill="#334155">ベル音＋マルチタップリバーブで番組らしさ演出</text>

  <!-- Ducking Envelope Box -->
  <rect x="344" y="96" width="224" height="148" rx="12" fill="#ffffff" stroke="#0891b2" stroke-width="2"/>
  <rect x="344" y="96" width="224" height="28" rx="12" fill="#0891b2"/>
  <text x="456" y="115" text-anchor="middle" font-family="sans-serif" font-size="11" font-weight="700" fill="#ffffff">先読みサイドチェイン・ダッキング</text>
  <!-- Mini Envelope Waveform -->
  <rect x="358" y="134" width="196" height="58" rx="6" fill="#0f172a"/>
  <path d="M 366 146 L 402 146 Q 416 146 424 176 L 490 176 Q 504 176 520 146 L 546 146" fill="none" stroke="#38bdf8" stroke-width="2.5"/>
  <rect x="422" y="138" width="70" height="14" rx="3" fill="#f43f5e" fill-opacity="0.35"/>
  <text x="457" y="149" text-anchor="middle" font-family="sans-serif" font-size="9" font-weight="700" fill="#fda4af">発話区間</text>
  <text x="384" y="160" text-anchor="middle" font-family="sans-serif" font-size="8" fill="#bae6fd">0.36</text>
  <text x="457" y="187" text-anchor="middle" font-family="sans-serif" font-size="8" fill="#7dd3fc">0.11 (0.16s先読み減衰)</text>
  <text x="456" y="210" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#334155">話し出す0.16秒前からBGMを</text>
  <text x="456" y="226" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#334155">スッと下げ、話終わりに余韻復帰</text>

  <line x1="300" y1="84" x2="340" y2="140" stroke="#334155" stroke-width="2" marker-end="url(#arr4)"/>
  <line x1="300" y1="170" x2="340" y2="170" stroke="#334155" stroke-width="2" marker-end="url(#arr4)"/>
  <line x1="300" y1="256" x2="340" y2="205" stroke="#334155" stroke-width="2" marker-end="url(#arr4)"/>

  <!-- Mastering Output -->
  <line x1="568" y1="170" x2="598" y2="170" stroke="#334155" stroke-width="2" marker-end="url(#arr4)"/>
  <rect x="602" y="76" width="234" height="188" rx="12" fill="#ffffff" stroke="#1b5e3c" stroke-width="2"/>
  <rect x="602" y="76" width="234" height="30" rx="12" fill="#1b5e3c"/>
  <text x="719" y="96" text-anchor="middle" font-family="sans-serif" font-size="12" font-weight="700" fill="#ffffff">FFmpeg 放送規格マスタリング</text>
  <text x="616" y="128" font-family="sans-serif" font-size="11" font-weight="700" fill="#124028">1. highpass=f=70</text>
  <text x="626" y="144" font-family="sans-serif" font-size="10" fill="#475569">70Hz以下の不要な超低域ノイズをカット</text>
  <text x="616" y="168" font-family="sans-serif" font-size="11" font-weight="700" fill="#124028">2. loudnorm I=-16 LUFS</text>
  <text x="626" y="184" font-family="sans-serif" font-size="10" fill="#475569">ポッドキャスト標準の聴きやすい音量へ均一化</text>
  <rect x="616" y="200" width="206" height="50" rx="8" fill="#e7f4ec"/>
  <text x="719" y="220" text-anchor="middle" font-family="sans-serif" font-size="11" font-weight="800" fill="#1b5e3c">出力：112kbps ステレオ MP3</text>
  <text x="719" y="238" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#124028">＋ 正確な秒数入り manifest.json</text>
</svg>
"""

SVG_DIAGRAM_5 = """
<svg viewBox="0 0 860 250" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="静的HTML生成とブラウザ同期字幕プレーヤーの仕組み">
  <defs>
    <marker id="arr5" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 1 L 10 5 L 0 9 z" fill="#1b5e3c"/>
    </marker>
  </defs>
  <rect width="860" height="250" rx="14" fill="#f8fafc"/>
  <text x="430" y="28" text-anchor="middle" font-family="sans-serif" font-size="15" font-weight="800" fill="#0f172a">図解⑤：サーバー不要でローカル＆ネット両対応！「HTML内蔵JSON ＆ 同期字幕プレーヤー」</text>

  <!-- Build Site -->
  <rect x="24" y="54" width="232" height="168" rx="12" fill="#ffffff" stroke="#1b5e3c" stroke-width="2"/>
  <rect x="24" y="54" width="232" height="30" rx="12" fill="#1b5e3c"/>
  <text x="140" y="74" text-anchor="middle" font-family="sans-serif" font-size="12" font-weight="700" fill="#ffffff">build_site.py（静的生成）</text>
  <text x="38" y="106" font-family="sans-serif" font-size="11" font-weight="700" fill="#124028">入力素材:</text>
  <text x="44" y="124" font-family="sans-serif" font-size="10" fill="#334155">• episode.json (台本・リンク)</text>
  <text x="44" y="140" font-family="sans-serif" font-size="10" fill="#334155">• manifest.json (開始/終了秒)</text>
  <text x="44" y="156" font-family="sans-serif" font-size="10" fill="#334155">• program_schedule.json</text>
  <rect x="38" y="168" width="204" height="42" rx="6" fill="#e7f4ec"/>
  <text x="140" y="186" text-anchor="middle" font-family="sans-serif" font-size="10" font-weight="700" fill="#1b5e3c">HTML内に &lt;script type="application/json"&gt;</text>
  <text x="140" y="201" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#124028">として丸ごと埋め込むため CORS 回避！</text>

  <line x1="256" y1="138" x2="294" y2="138" stroke="#1b5e3c" stroke-width="2" marker-end="url(#arr5)"/>

  <!-- Output HTML -->
  <rect x="298" y="54" width="224" height="168" rx="12" fill="#ffffff" stroke="#0284c7" stroke-width="2"/>
  <rect x="298" y="54" width="224" height="30" rx="12" fill="#0284c7"/>
  <text x="410" y="74" text-anchor="middle" font-family="sans-serif" font-size="12" font-weight="700" fill="#ffffff">docs/ 公開ファイル群</text>
  <text x="314" y="106" font-family="sans-serif" font-size="10" fill="#1e293b">• index.html（最新回プレーヤー）</text>
  <text x="314" y="124" font-family="sans-serif" font-size="10" fill="#1e293b">• calendar.html（放送カレンダー）</text>
  <text x="314" y="142" font-family="sans-serif" font-size="10" fill="#1e293b">• archive.html（過去回検索）</text>
  <text x="314" y="160" font-family="sans-serif" font-size="10" fill="#1e293b">• cast.html / characters.html</text>
  <text x="314" y="178" font-family="sans-serif" font-size="10" fill="#1e293b">• tech.html（この技術解説）</text>
  <text x="314" y="198" font-family="sans-serif" font-size="10" font-weight="700" fill="#0369a1">ネット(Pages)でも PC直開き(file://)でも動作</text>

  <line x1="522" y1="138" x2="560" y2="138" stroke="#1b5e3c" stroke-width="2" marker-end="url(#arr5)"/>

  <!-- Browser Sync Loop -->
  <rect x="564" y="54" width="272" height="168" rx="12" fill="#ffffff" stroke="#d97706" stroke-width="2"/>
  <rect x="564" y="54" width="272" height="30" rx="12" fill="#d97706"/>
  <text x="700" y="74" text-anchor="middle" font-family="sans-serif" font-size="12" font-weight="700" fill="#ffffff">ブラウザ内の同期ループ (JS)</text>
  <rect x="578" y="96" width="244" height="46" rx="8" fill="#fffbeb"/>
  <text x="700" y="114" text-anchor="middle" font-family="sans-serif" font-size="11" font-weight="700" fill="#92400e">① 音声再生 → timeupdate イベント</text>
  <text x="700" y="131" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#475569">現在秒数に合うセリフを自動ハイライト＆追従</text>
  <rect x="578" y="156" width="244" height="50" rx="8" fill="#ecfeff"/>
  <text x="700" y="174" text-anchor="middle" font-family="sans-serif" font-size="11" font-weight="700" fill="#0e7490">② 台本タップ → 逆引きシーク</text>
  <text x="700" y="191" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#475569">audio.currentTime = start_sec で即ジャンプ</text>
</svg>
"""

SVG_DIAGRAM_6 = """
<svg viewBox="0 0 860 245" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="GitHub Actionsの自動運転タイムラインとcron遅延対策">
  <rect width="860" height="245" rx="14" fill="#f8fafc"/>
  <text x="430" y="28" text-anchor="middle" font-family="sans-serif" font-size="15" font-weight="800" fill="#0f172a">図解⑥：GitHub Actions「早朝二重起動 ＆ 冪等（べきとう）ガード」タイムライン</text>

  <!-- Main Timeline Axis -->
  <line x1="48" y1="125" x2="812" y2="125" stroke="#94a3b8" stroke-width="4" stroke-linecap="round"/>

  <!-- Node 1: Sun 12:17 -->
  <circle cx="110" cy="125" r="10" fill="#7c3aed"/>
  <rect x="30" y="48" width="160" height="60" rx="8" fill="#f5f3ff" stroke="#7c3aed" stroke-width="1.8"/>
  <text x="110" y="68" text-anchor="middle" font-family="sans-serif" font-size="11" font-weight="800" fill="#5b21b6">日曜 12:17 JST</text>
  <text x="110" y="84" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#334155">編集長AI 週次編成</text>
  <text x="110" y="99" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#334155">カレンダー＆Pages更新</text>

  <!-- Node 2: Daily 05:17 -->
  <circle cx="320" cy="125" r="10" fill="#0284c7"/>
  <rect x="230" y="144" width="180" height="74" rx="8" fill="#f0f9ff" stroke="#0284c7" stroke-width="1.8"/>
  <text x="320" y="164" text-anchor="middle" font-family="sans-serif" font-size="11" font-weight="800" fill="#0369a1">毎日 05:17 JST (第1起動)</text>
  <text x="320" y="181" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#334155">7時放送へ約1時間40分の余裕</text>
  <text x="320" y="196" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#334155">混雑を避けたオフピーク分 (:17)</text>
  <text x="320" y="210" text-anchor="middle" font-family="sans-serif" font-size="10" font-weight="700" fill="#0284c7">台本生成・TTS合成・Pages公開</text>

  <!-- Node 3: Daily 06:13 -->
  <circle cx="545" cy="125" r="10" fill="#d97706"/>
  <rect x="448" y="48" width="194" height="62" rx="8" fill="#fffbeb" stroke="#d97706" stroke-width="1.8"/>
  <text x="545" y="68" text-anchor="middle" font-family="sans-serif" font-size="11" font-weight="800" fill="#b45309">毎日 06:13 JST (予備起動)</text>
  <text x="545" y="84" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#334155">05:17が欠損・大幅遅延時に救済</text>
  <text x="545" y="99" text-anchor="middle" font-family="sans-serif" font-size="10" font-weight="700" fill="#92400e">既に当日MP3があれば安全スキップ</text>

  <!-- Node 4: 07:00 Broadcast -->
  <circle cx="755" cy="125" r="12" fill="#1b5e3c"/>
  <rect x="678" y="144" width="154" height="74" rx="8" fill="#e7f4ec" stroke="#1b5e3c" stroke-width="2"/>
  <text x="755" y="166" text-anchor="middle" font-family="sans-serif" font-size="12" font-weight="800" fill="#124028">毎朝 07:00 JST</text>
  <text x="755" y="185" text-anchor="middle" font-family="sans-serif" font-size="11" font-weight="700" fill="#1b5e3c">ラジオ番組 配信開始！</text>
  <text x="755" y="203" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#334155">スマホ・PCからいつでも聴取可</text>
</svg>
"""

TECH_HTML_TEMPLATE = Template("""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>番組のしくみ・技術解説 | 毎朝7時！こだいら防災＆まちラジオ</title>
  <style>
$COMMON_CSS
$TECH_CSS
  </style>
</head>
<body>
  <header>
    <div class="header-inner">
      $NAV_HTML
    </div>
  </header>

  <main class="container single">
    <div class="card tech-hero">
      <span class="tech-hero-badge">SPECIAL TECHNICAL GUIDE ＋ 15分解説対談</span>
      <h2>小春・平蔵・AIオーケストレーター ネオンさんが語る「こだいら防災＆まちラジオ」ができるまで</h2>
      <p>
        「毎朝7時に、小平の最新ニュースや天気・地震・専門家の防災解説がラジオ音声と同期サイトになって届く」――この番組が裏側でどんな技術と工夫を組み合わせて作られているのかを、<strong>特別対談音声（約15分）</strong>と<strong>図解付きの技術解説</strong>で、初めての方にもわかりやすく、技術的にも正確・具体的にご紹介します。
      </p>
    </div>

    <div class="card toc-card">
      <div class="toc-title">ページ内クイックジャンプ</div>
      <div class="toc-row">
        <a class="toc-pill" href="#audio-talk">🎧 約15分 解説対談音声</a>
        <a class="toc-pill" href="#sec-1">1. 全体像</a>
        <a class="toc-pill" href="#sec-2">2. 情報収集・記憶</a>
        <a class="toc-pill" href="#sec-3">3. 3段階AI・校閲</a>
        <a class="toc-pill" href="#sec-4">4. 音声TTS・数式BGM</a>
        <a class="toc-pill" href="#sec-5">5. 静的サイト・同期</a>
        <a class="toc-pill" href="#sec-6">6. GitHub自動化</a>
        <a class="toc-pill" href="#sec-7">7. ファイル構成表</a>
      </div>
    </div>

    <!-- Embedded ~15-min Roundtable Player -->
    <div class="card tech-player-wrap" id="audio-talk">
      <div class="section-head">
        <h2>🎧 特別対談音声：小春 × 平蔵 × AIオーケストレーター ネオンさん</h2>
        <span class="hint" id="tech-dur-hint">$TECH_DUR_HINT</span>
      </div>
      <div style="padding: 0.85rem 1rem; border-bottom: 1px solid var(--border); background:#f8fafc;">
        <div id="tech-audio-pending" class="audio-pending-banner" style="display:none;">
          この特別対談音声MP3はまだ生成されていません。<code>python src/generate_tech_talk.py</code> および <code>build_radio.py</code> を実行すると音声再生ができます。下の全編台本はそのままお読みいただけます。
        </div>
        <audio id="tech-audio" preload="metadata"></audio>
        <div class="now-playing">
          <div class="now-chapter" id="tech-now-chapter">再生ボタンを押して特別対談をお聴きください</div>
          <div class="time-readout" id="tech-time-readout">00:00 / $TECH_DUR_FMT</div>
        </div>
        <input type="range" class="scrubber" id="tech-scrubber" min="0" max="900" step="0.1" value="0" aria-label="技術解説対談 シークバー" />
        <div class="controls">
          <div class="btn-group">
            <button type="button" class="primary" id="tech-btn-play">▶ 対談を再生</button>
            <button type="button" id="tech-btn-back">-15s</button>
            <button type="button" id="tech-btn-fwd">+15s</button>
          </div>
          <div class="btn-group speed-group" id="tech-speed-group">
            <button type="button" data-rate="0.9">0.9x</button>
            <button type="button" data-rate="1" class="is-selected">1.0x</button>
            <button type="button" data-rate="1.15">1.15x</button>
            <button type="button" data-rate="1.25">1.25x</button>
          </div>
          <div class="btn-group">
            <button type="button" id="tech-btn-speed-cycle" class="speed-cycle-btn">1.0x</button>
            <button type="button" id="tech-btn-autoscroll" class="active-toggle">追従ON</button>
          </div>
        </div>
      </div>

      <details class="chapter-details" id="tech-chapter-details" open>
        <summary class="section-head chapter-summary">
          <h2>対談チャプター目次（タップで再生ジャンプ）</h2>
          <span class="hint">開閉</span>
        </summary>
        <div class="chapter-list" id="tech-chapter-list"></div>
      </details>

      <details open>
        <summary class="section-head chapter-summary">
          <h2>同期対談台本（セリフをタップで音声ジャンプ）</h2>
          <span class="hint">開閉</span>
        </summary>
        <div class="tech-transcript-wrap" id="tech-transcript-body"></div>
      </details>
    </div>

    <!-- Chapter 1 -->
    <section class="card tech-chapter" id="sec-1">
      <div class="section-head">
        <h2>1. 全体像 ― AIオーケストレーションで毎朝届くラジオ番組</h2>
        <span class="hint">システム全体の設計思想</span>
      </div>
      <div class="tech-body">
        <p>
          このラジオ番組は、人間のスタジオ収録ではなく、<strong>Python（パイソン）</strong>で組まれた制作システムが毎朝自動で作っています。ただし、「1つのAIに『今日小平市のラジオ台本を書いて』と丸投げする」のではありません。役割ごとに得意なツールやAIモデルを指揮者のように連携させる<strong>「AIオーケストレーション」</strong>という考え方で作られています。
        </p>
        <div class="beginner-box">
          <strong>🔰 かみ砕きメモ：「AIオーケストレーション」ってなに？</strong>
          オーケストラにバイオリン・トランペット・打楽器それぞれの名手がいて、指揮者がタイミングを合わせて1つの交響曲を作るように、「調べるのが得意なAI」「おしゃべり台本を書くのが得意なAI」「ミスをチェックするAI」「声を出して演技するAI」「計算して音楽を鳴らすプログラム」を組み合わせることで、1人（1つのAI）では絶対に届かない正確さと温かさを実現する仕組みです。
        </div>
        <figure class="diagram-figure">
          $SVG_DIAGRAM_1
          <figcaption class="diagram-caption">図解①：毎朝5:17の起動から7:00のWeb配信までを自動連携させる全体パイプライン</figcaption>
        </figure>
      </div>
    </section>

    <!-- Chapter 2 -->
    <section class="card tech-chapter" id="sec-2">
      <div class="section-head">
        <h2>2. ステップ1 ― 今朝の天気・地震・カレンダー・長期記憶を集める</h2>
        <span class="hint">src/live_feeds.py ・ src/schedule_calendar.py</span>
      </div>
      <div class="tech-body">
        <p>
          ラジオらしさの命は「まさに今朝の天気」と「昨日の話題と被らない連続性」です。台本を書き始める前に、プログラムは外部の公的・オープンAPIとリポジトリ内の記憶データを一気に集めます。
        </p>
        <div class="beginner-box">
          <strong>🔰 かみ砕きメモ：「API（エーピーアイ）」ってなに？</strong>
          プログラム同士がデータを受け渡しするための「レストランの注文窓口」です。私たちがWebブラウザで天気サイトを目で見て確認する代わりに、Pythonプログラムが <code>https://api.open-meteo.com/...</code> という窓口に注文票を送ると、小平市の気温・湿度・降水確率が整理されたデータ（JSON形式）で1秒以内に返ってきます。
        </div>
        <div class="tech-grid-2">
          <div class="tech-mini-card">
            <h4>☁ Open-Meteo API（小平市のピンポイント天気）</h4>
            <code>src/live_feeds.py</code> が小平市中心の緯度・経度（<strong>35.7285, 139.4775</strong>）を指定して、今朝の気温・湿度・風速・3日間予報を取得。前後の気温差が9℃以上なら「寒暖差注意」、湿度45%以下なら「乾燥・火の元注意」といった番組用アドバイスも自動生成します。
          </div>
          <div class="tech-mini-card">
            <h4>🌋 P2PQuake API v2（緊急地震トリガー）</h4>
            直近48時間の地震履歴（<code>codes=551</code>）を取得。もし<strong>関東・東京で震度4以上</strong>、<strong>全国で震度5弱以上</strong>、または津波警報・注意報を検知した場合は、通常構成に<strong>+4分の緊急防災コーナー（special_feature）</strong>を自動追加して放送尺を拡張します。
          </div>
          <div class="tech-mini-card">
            <h4>📅 jpholiday ＆ 特別日・事前編成カレンダー</h4>
            日本の祝日判定ライブラリ <code>jpholiday</code> により、土日だけでなく祝日（例：11/23 勤労感謝の日）も<strong>平日10分（約3,200字）から15分拡大版（約4,800字）</strong>へ自動切替。さらに <code>config/special_days.json</code> で記念日カウントダウン、<code>config/program_schedule.json</code> で先々の専門家テーマや変更リクエストを管理し、<code>resolve_tomorrow_preview()</code> が明日の予告まで自動計算します。
          </div>
          <div class="tech-mini-card">
            <h4>🧠 28日＆90日の重複防止メモリ</h4>
            <code>data/topic_history.json</code> と <code>data/knowledge_log.json</code> により、<strong>小平の街ネタは直近28日間</strong>、<strong>7人の専門家の解説キーワードは過去90日間（約3か月）</strong>同じテーマを繰り返さないよう <code>build_dedup_context()</code> が自動ガード。小春たちの「前に学んだあれですね！」という成長描写にも活用されます。
          </div>
        </div>
        <figure class="diagram-figure">
          $SVG_DIAGRAM_2
          <figcaption class="diagram-caption">図解②：ライブAPI・祝日判定・事前編成カレンダー・長期記憶が台本生成の前に合流する構造</figcaption>
        </figure>
      </div>
    </section>

    <!-- Chapter 3 -->
    <section class="card tech-chapter" id="sec-3">
      <div class="section-head">
        <h2>3. ステップ2 ― 3段階ハイブリッドAI制作 ＆ 自動ファクトチェック</h2>
        <span class="hint">src/generate_episode.py ・ src/plan_weekly_editorial.py</span>
      </div>
      <div class="tech-body">
        <p>
          台本づくりは<strong>「Phase A：調査」「Phase B：台本執筆」「Phase C：ファクトチェック＆自動校閲」</strong>の3段階パイプラインで構成されています。それぞれ得意分野の異なるモデル <code>gemini-4-hydrogen</code> と <code>gemini-4-neon</code> をリレーさせています。
        </p>
        <div class="beginner-box">
          <strong>🔰 かみ砕きメモ：なぜAIが嘘をつくことがあるの？どう防いでるの？</strong>
          大規模言語モデル（LLM）は学習時の記憶をもとに自然な文章を紡ぐのが得意ですが、最新の地域イベント日程などを記憶だけで書くと、昨年の日付と混ぜてしまう<strong>ハルシネーション（もっともらしい誤情報）</strong>が起きることがあります。そこで本番組では、まず <strong>Google検索グラウンディング（検索結果に根拠を置く仕組み）</strong> で今年の一次情報を調べ（Phase A）、執筆後に別の校閲AIがもう一度Google検索で裏取りをする（Phase C）二重の安全網を敷いています。
        </div>
        <figure class="diagram-figure">
          $SVG_DIAGRAM_3
          <figcaption class="diagram-caption">図解③：調査（Hydrogen）→ 執筆（Neon）→ 自動校閲（Hydrogen）の3フェーズ制作リレー</figcaption>
        </figure>

        <h3>台本データは「読む用」と「しゃべる用」を分けている（JSON構造化出力）</h3>
        <p>
          Phase B の <code>gemini-4-neon</code> は単なる自由文章ではなく、<strong>JSON（ジェイソン）</strong>というプログラムがそのまま読み取れる設計図の形で台本を出力します。ここで非常に重要なのが、1つのセリフの中に<strong>画面表示用の <code>text</code></strong> と<strong>音声合成用の <code>tts_text</code></strong> の2種類を持たせている点です。
        </p>
        <div class="code-sample"><span class="code-comment">// episodes/YYYY-MM-DD/episode.json に保存される1セリフ分の構造</span>
{
  "speaker": "koharu",
  "text": "小平駅南口から小川町まで、防災マップアプリを見ながら歩いてみたいです！", <span class="code-comment">// 画面表示用（タグなし）</span>
  "tts_text": "こだいらえき みなみぐちから おがわちょうまで、&lt;short pause&gt; ぼうさいマップアプリを みながら あるいてみたいです！&lt;laugh&gt;", <span class="code-comment">// 読み上げ用（かな＋感情タグ）</span>
  "style": "bright, cheerful, curious Japanese morning radio host", <span class="code-comment">// 英語の演技ディレクション</span>
  "pause_after": 0.34 <span class="code-comment">// 次の人が話すまでの「間」（秒）</span>
}</div>
        <div class="tech-spec-box">
          <strong>Phase C の「小春キャラクター保護」校閲ルール：</strong>
          ファクトチェックAIは全セリフの日程・数値（耐震基準年や胸骨圧迫のテンポ100〜120回/分など）を厳しく検証し、誤りがあれば <code>=== FACT_CHECK_JSON ===</code> という修正パッチで該当行だけをピンポイント書き換えします。ただし、<strong>「小春が初心者としてお茶目に予想して、すぐ次のターンで平蔵や専門家が優しく訂正している箇所」</strong>は番組の大切な演出として残すよう設計されています。
        </div>
      </div>
    </section>

    <!-- Chapter 4 -->
    <section class="card tech-chapter" id="sec-4">
      <div class="section-head">
        <h2>4. ステップ3 ― 声の演技（Gemini 3.8 Flash TTS）＆ NumPy数式BGM・音響DSP</h2>
        <span class="hint">src/build_radio.py ・ src/bgm_synth.py</span>
      </div>
      <div class="tech-body">
        <p>
          完成した台本JSONを受け取るのが <code>src/build_radio.py</code> と <code>src/bgm_synth.py</code> です。ここでは声の合成だけでなく、本物のFMラジオ局のミキサー卓と同じデジタル信号処理（DSP）をPythonとNumPy・FFmpegで行っています。
        </p>
        <div class="beginner-box">
          <strong>🔰 かみ砕きメモ：著作権フリー！BGMを「数式」から作ってるって本当？</strong>
          はい！インターネット上の音楽素材をダウンロードするのではなく、<code>src/bgm_synth.py</code> の中で<strong>NumPy（ナムパイ）という数値計算ライブラリを使い、高校数学で習うサイン波（sin）を何重にも足し合わせて楽器の音色をゼロから合成</strong>しています。ローズ風の温かなエレキピアノも、朝のチャイムも、小鳥のようなベル音も、すべてプログラムが毎回44,100Hzの音の波として計算し、自然な残響（マルチタップ・リバーブ）をかけて生み出しています。
        </div>
        <figure class="diagram-figure">
          $SVG_DIAGRAM_4
          <figcaption class="diagram-caption">図解④：TTS音声・数式BGM・ジングルを0.16秒先読みダッキングで合成し、-16 LUFSへ仕上げる音響回路</figcaption>
        </figure>

        <div class="tech-grid-2">
          <div class="tech-mini-card">
            <h4>🎙 2話者・4ターン・420文字ブロック分割とキャッシュ</h4>
            <code>gemini-3.8-flash-tts</code> のマルチスピーカーAPIは1リクエストで2話者まで自然な掛け合いを生成できます。<code>_group_lines_into_blocks()</code> が台本を「最大2話者・4ターン・420文字以内」に賢く束ねてAPI回数を抑え（15分番組でも約17〜25回程度）、さらに内容を <strong>SHA-256ハッシュ値</strong> で <code>.cache/tts_gemini/</code> に保存するため、台本の1行だけ直して再ビルドする際も変更行以外はAPIを再消費しません。
          </div>
          <div class="tech-mini-card">
            <h4>🎚 先読みダッキング ＆ ポッドキャスト基準 -16 LUFS</h4>
            BGMがしゃべりを邪魔しないよう、<code>_compute_ducking_envelope()</code> が<strong>話し始める0.16秒前から先読みして</strong>BGM音量を <code>0.36</code> から <code>0.11</code> へ滑らかに下げます（BGM自体も <code>4,200 Hz</code> のローパスフィルタで声の帯域を空けています）。最後は <code>FFmpeg</code> で <code>70 Hz</code> 以下の低域ノイズを除去し、世界標準のラウドネス規格 <strong>-16 LUFS</strong> に整えて <code>112 kbps</code> MP3 と秒数台帳 <code>manifest.json</code> を書き出します。
          </div>
        </div>

        <h3>出演者・AIゲストの専用ボイス＆ステレオ定位割り当て</h3>
        <div class="tech-table-wrap">
          <table class="tech-table">
            <thead>
              <tr>
                <th>出演者 / 担当</th>
                <th>役割・テーマ</th>
                <th>Gemini 3.8 TTS ボイス名</th>
                <th>ステレオ定位 / 特徴</th>
              </tr>
            </thead>
            <tbody>
              $VOICE_ROWS_HTML
            </tbody>
          </table>
        </div>
      </div>
    </section>

    <!-- Chapter 5 -->
    <section class="card tech-chapter" id="sec-5">
      <div class="section-head">
        <h2>5. ステップ4 ― サーバー不要で動く静的ポータル ＆ 同期字幕プレーヤー</h2>
        <span class="hint">src/build_site.py ・ docs/</span>
      </div>
      <div class="tech-body">
        <p>
          多くのWebサービスでは裏側でデータベースやプログラムサーバーを24時間動かしますが、この番組は <code>src/build_site.py</code> が<strong>HTML・CSS・JavaScript・MP3だけの「静的ファイル群（docs/）」</strong>を丸ごと生成します。
        </p>
        <div class="beginner-box">
          <strong>🔰 かみ砕きメモ：なぜ「静的サイト」＋「HTML内JSON埋め込み」なの？</strong>
          通常のブラウザはセキュリティ保護（CORS制限）のため、ネットサーバーを通さずにPC上のHTMLファイルをダブルクリック（<code>file://</code>）すると外部のJSONファイルを読み込めません。そこで本サイトは、台本やタイムライン・カレンダー情報をすべてHTMLページの中の <code>&lt;script type="application/json"&gt;</code> タグへ直接埋め込んでいます。これにより、GitHub Pagesでの公開はもちろん、<strong>オフラインのWindowsパソコンで直接開いても100%同じように同期再生・検索ができます。</strong>
        </div>
        <figure class="diagram-figure">
          $SVG_DIAGRAM_5
          <figcaption class="diagram-caption">図解⑤：build_site.py によるHTML生成と、ブラウザ内 audio.timeupdate による双方向シンク</figcaption>
        </figure>
      </div>
    </section>

    <!-- Chapter 6 -->
    <section class="card tech-chapter" id="sec-6">
      <div class="section-head">
        <h2>6. ステップ5 ― クラウド自動放送局（GitHub Actions・cron遅延対策・Secrets）</h2>
        <span class="hint">.github/workflows/daily-radio.yml ・ weekly-editorial.yml</span>
      </div>
      <div class="tech-body">
        <p>
          自分のパソコンの電源を毎朝6時に点けておかなくても、<strong>GitHub Actions</strong> というクラウド上の仮想コンピュータ（Ubuntu Linux）が決められた時刻に自動で起動し、台本生成から音声合成・GitHubへの保存・GitHub Pages公開までを実行します。
        </p>
        <div class="beginner-box">
          <strong>🔰 かみ砕きメモ：2026年11月23日朝の遅延と「二重起動＋冪等（べきとう）設計」への強化</strong>
          GitHub Actionsの無料枠の定期実行（<code>cron</code>）は、世界の多くの人が使う時間帯だと数十分〜数時間ほど実行キューで待たされることがあります。実際に11月23日朝は、従来の <code>06:35 JST</code> 設定がキュー混雑で7時までに発火しない事象が確認されました。そこで同日、① <strong>朝05:17 JST（約1時間40分の余裕）</strong> と <strong>朝06:13 JST（予備キャッチアップ）</strong> のオフピーク2段構えへ変更し、② <strong>すでに当日のJSONとMP3が存在すればスキップする「冪等（何度走っても壊れない）チェック」</strong>を組み込みました。さらに日曜の編集長AIも <strong>日曜昼12:17 JST</strong> に前倒ししてカレンダーページまで即更新します。
        </div>
        <figure class="diagram-figure">
          $SVG_DIAGRAM_6
          <figcaption class="diagram-caption">図解⑥：日曜12:17の編集長AI編成と、毎朝05:17／06:13の二重バックアップ自動運転タイムライン</figcaption>
        </figure>
        <div class="tech-spec-box">
          <strong>🔐 APIキーの安全管理（GitHub Secrets）：</strong>
          Gemini APIキーは課金や利用枠に直結するため、ソースコードや公開リポジトリには絶対に書き込みません。手元では <code>.gitignore</code> で除外された <code>.env</code> ファイル、クラウド上では暗号化金庫である <strong>GitHub Secrets</strong>（<code>GEMINI_API_KEY</code>）に保管し、実行中の仮想マシンのメモリ内だけに安全に渡しています。
        </div>
      </div>
    </section>

    <!-- Chapter 7 -->
    <section class="card tech-chapter" id="sec-7">
      <div class="section-head">
        <h2>7. リポジトリ構成・主要ファイルリファレンス一覧</h2>
        <span class="hint">設計書マップ</span>
      </div>
      <div class="tech-body">
        <div class="tech-table-wrap">
          <table class="tech-table">
            <thead>
              <tr>
                <th>パス / ファイル</th>
                <th>役割（何をする場所か）</th>
              </tr>
            </thead>
            <tbody>
              <tr><td><code>config/characters.json</code></td><td>小春・平蔵のキャラクター設定、TTSボイス名・パン定位・連続成長ルール</td></tr>
              <tr><td><code>config/weekly_themes.json</code></td><td>月〜日の7つの防災テーマ、7人の専門家ゲスト設定、各10個の解説キーワードバンク</td></tr>
              <tr><td><code>config/special_days.json</code></td><td>1/17、3/11、9/1などの年次防災記念日＆小平イベントのカウントダウン設定</td></tr>
              <tr><td><code>config/program_schedule.json</code></td><td>先々までの専門家解説テーマ事前予定・リスナーリクエスト管理（カレンダーと連動）</td></tr>
              <tr><td><code>data/editorial_plan.json</code></td><td>編集長AIが週単位で作成した週間テーマ軸・エリア別切り口・特別特集</td></tr>
              <tr><td><code>data/topic_history.json</code> / <code>knowledge_log.json</code></td><td>28日小平ネタ・90日専門家用語の重複防止履歴と、小春たちの防災発見ノート</td></tr>
              <tr><td><code>src/live_feeds.py</code></td><td>Open-Meteo（小平気象）＆ P2PQuake v2（地震）ライブ取得・緊急特集判定</td></tr>
              <tr><td><code>src/schedule_calendar.py</code></td><td><code>jpholiday</code> 祝日判定、特別日・編集長プラン・事前編成統合、明日の予告生成</td></tr>
              <tr><td><code>src/generate_episode.py</code></td><td>Phase A (Hydrogen検索) → Phase B (Neon台本) → Phase C (Hydrogen校閲) 実行本体</td></tr>
              <tr><td><code>src/plan_weekly_editorial.py</code></td><td>日曜稼働の編集長AI（2週間先行リサーチ＆事前編成を尊重した週別マージ）</td></tr>
              <tr><td><code>src/bgm_synth.py</code> / <code>src/build_radio.py</code></td><td>NumPy数式BGM/ジングル生成、Gemini 3.8 Flash TTS合成、先読みダッキング、-16 LUFS MP3出力</td></tr>
              <tr><td><code>src/generate_tech_talk.py</code></td><td>小春×平蔵×ネオンさんの技術解説対談スクリプト生成（<code>data/tech_talk/</code> へ格納）</td></tr>
              <tr><td><code>src/build_site.py</code> / <code>src/site_*.py</code></td><td><code>docs/</code> 配下の最新回・カレンダー・過去回・出演者・防災ノート・技術解説ページ静的生成</td></tr>
              <tr><td><code>.github/workflows/daily-radio.yml</code> / <code>weekly-editorial.yml</code></td><td>毎日05:17/06:13 JST自動放送＆Pages公開、日曜12:17 JST週間編成＆カレンダー更新</td></tr>
            </tbody>
          </table>
        </div>
        <div style="display:flex; flex-wrap:wrap; gap:0.55rem; margin-top:0.2rem;">
          <a class="btn-link" href="index.html">最新回のラジオを聴く →</a>
          <a class="btn-link" href="calendar.html">放送内容カレンダーを見る →</a>
          <a class="btn-link" href="cast.html">出演者プロフィール＆ボイス →</a>
        </div>
      </div>
    </section>
  </main>

  <footer>毎朝7時！こだいら防災＆まちラジオ（東京都小平市）／ AIオーケストレーション技術ガイド</footer>

  <script type="application/json" id="tech-talk-data">$PAYLOAD_JSON</script>
  <script>
    (function () {
      const data = JSON.parse(document.getElementById("tech-talk-data").textContent);
      const audio = document.getElementById("tech-audio");
      const btnPlay = document.getElementById("tech-btn-play");
      const btnBack = document.getElementById("tech-btn-back");
      const btnFwd = document.getElementById("tech-btn-fwd");
      const btnAutoScroll = document.getElementById("tech-btn-autoscroll");
      const btnSpeedCycle = document.getElementById("tech-btn-speed-cycle");
      const scrubber = document.getElementById("tech-scrubber");
      const timeReadout = document.getElementById("tech-time-readout");
      const nowChapter = document.getElementById("tech-now-chapter");
      const chapterList = document.getElementById("tech-chapter-list");
      const transcriptBody = document.getElementById("tech-transcript-body");
      const speedButtons = Array.from(document.querySelectorAll("#tech-speed-group button"));

      const speedRates = [1.0, 1.15, 1.25, 1.5, 0.9];
      let speedIdx = 0;
      let autoScroll = true;
      let isScrubbing = false;
      let lastActiveLineIdx = -1;
      let lastActiveSegId = null;

      function fmtTime(sec) {
        const s = Math.max(0, Math.floor(sec || 0));
        return String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
      }

      if (data.has_audio) {
        audio.src = data.audio_src;
      } else {
        document.getElementById("tech-audio-pending").style.display = "block";
        btnPlay.disabled = true;
        btnBack.disabled = true;
        btnFwd.disabled = true;
        scrubber.disabled = true;
      }

      const totalEst = data.total_duration_sec || 900;
      scrubber.max = String(totalEst);
      timeReadout.textContent = "00:00 / " + fmtTime(totalEst);

      const chapterButtons = new Map();
      const flatLines = [];

      (data.segments || []).forEach((seg, segIdx) => {
        const cBtn = document.createElement("button");
        cBtn.type = "button";
        cBtn.className = "chapter-btn";
        const tcSpanTop = document.createElement("span");
        tcSpanTop.className = "chapter-tc";
        tcSpanTop.textContent = fmtTime(seg.start_sec) + " 〜 " + fmtTime(seg.end_sec);
        const titleSpanTop = document.createElement("span");
        titleSpanTop.className = "chapter-title";
        titleSpanTop.textContent = (segIdx + 1) + ". " + seg.title;
        cBtn.appendChild(tcSpanTop);
        cBtn.appendChild(titleSpanTop);
        cBtn.addEventListener("click", () => {
          if (!data.has_audio) return;
          audio.currentTime = seg.start_sec;
          audio.play().catch(() => {});
        });
        chapterList.appendChild(cBtn);
        chapterButtons.set(seg.id, cBtn);

        const divEl = document.createElement("div");
        divEl.className = "seg-divider";
        const sTitle = document.createElement("span");
        sTitle.textContent = (segIdx + 1) + ". " + seg.title;
        const sTc = document.createElement("span");
        sTc.className = "chapter-tc";
        sTc.textContent = fmtTime(seg.start_sec);
        divEl.appendChild(sTitle);
        divEl.appendChild(sTc);
        transcriptBody.appendChild(divEl);

        (seg.lines || []).forEach((line) => {
          const row = document.createElement("div");
          row.className = "line-item";
          const tc = document.createElement("span");
          tc.className = "line-tc";
          tc.textContent = fmtTime(line.start_sec);

          const sp = document.createElement("span");
          sp.className = "speaker-pill " + (line.speaker === "guest" ? "speaker-neon" : ("speaker-" + line.speaker));
          sp.textContent = line.speaker_name;

          const txt = document.createElement("span");
          txt.className = "line-text";
          txt.textContent = line.text;

          row.appendChild(tc);
          row.appendChild(sp);
          row.appendChild(txt);
          row.addEventListener("click", () => {
            if (!data.has_audio) return;
            audio.currentTime = line.start_sec;
            audio.play().catch(() => {});
          });
          transcriptBody.appendChild(row);
          flatLines.push({ ...line, segId: seg.id, segTitle: seg.title, el: row });
        });
      });

      function applySpeed(rate) {
        audio.playbackRate = rate;
        btnSpeedCycle.textContent = rate + "x";
        speedButtons.forEach((b) => {
          b.classList.toggle("is-selected", parseFloat(b.dataset.rate || "1") === rate);
        });
      }

      function updateSyncUI() {
        const cur = audio.currentTime || 0;
        const total = Number.isFinite(audio.duration) ? audio.duration : totalEst;
        if (!isScrubbing) {
          scrubber.max = String(total || totalEst);
          scrubber.value = String(cur);
        }
        timeReadout.textContent = fmtTime(cur) + " / " + fmtTime(total);

        if (!data.segments || data.segments.length === 0) return;
        let activeSeg = data.segments[0];
        for (const seg of data.segments) {
          if (cur >= seg.start_sec) activeSeg = seg;
        }
        if (activeSeg && activeSeg.id !== lastActiveSegId) {
          if (lastActiveSegId && chapterButtons.has(lastActiveSegId)) {
            chapterButtons.get(lastActiveSegId).classList.remove("active");
          }
          if (chapterButtons.has(activeSeg.id)) {
            chapterButtons.get(activeSeg.id).classList.add("active");
          }
          nowChapter.textContent = activeSeg.title;
          lastActiveSegId = activeSeg.id;
        }

        let activeLineIdx = -1;
        for (let i = 0; i < flatLines.length; i++) {
          const l = flatLines[i];
          if (cur >= l.start_sec && cur <= l.end_sec + 0.35) {
            activeLineIdx = i;
            break;
          }
          if (cur >= l.start_sec) activeLineIdx = i;
        }
        if (activeLineIdx !== lastActiveLineIdx) {
          if (lastActiveLineIdx >= 0 && flatLines[lastActiveLineIdx]) {
            flatLines[lastActiveLineIdx].el.classList.remove("active");
          }
          if (activeLineIdx >= 0 && flatLines[activeLineIdx]) {
            const activeEl = flatLines[activeLineIdx].el;
            activeEl.classList.add("active");
            if (autoScroll && !audio.paused) {
              activeEl.scrollIntoView({ block: "nearest", behavior: "smooth" });
            }
          }
          lastActiveLineIdx = activeLineIdx;
        }
      }

      btnPlay.addEventListener("click", () => {
        if (!data.has_audio) return;
        if (audio.paused) audio.play().catch(() => {});
        else audio.pause();
      });
      btnBack.addEventListener("click", () => {
        if (!data.has_audio) return;
        audio.currentTime = Math.max(0, audio.currentTime - 15);
        updateSyncUI();
      });
      btnFwd.addEventListener("click", () => {
        if (!data.has_audio) return;
        const total = Number.isFinite(audio.duration) ? audio.duration : totalEst;
        audio.currentTime = Math.min(total, audio.currentTime + 15);
        updateSyncUI();
      });
      btnAutoScroll.addEventListener("click", () => {
        autoScroll = !autoScroll;
        btnAutoScroll.textContent = autoScroll ? "追従ON" : "追従OFF";
        btnAutoScroll.classList.toggle("active-toggle", autoScroll);
      });
      speedButtons.forEach((btn) => {
        btn.addEventListener("click", () => {
          const rate = parseFloat(btn.dataset.rate || "1");
          const found = speedRates.indexOf(rate);
          if (found >= 0) speedIdx = found;
          applySpeed(rate);
        });
      });
      btnSpeedCycle.addEventListener("click", () => {
        speedIdx = (speedIdx + 1) % speedRates.length;
        applySpeed(speedRates[speedIdx]);
      });
      scrubber.addEventListener("input", () => {
        isScrubbing = true;
        const total = Number.isFinite(audio.duration) ? audio.duration : totalEst;
        timeReadout.textContent = fmtTime(Number(scrubber.value)) + " / " + fmtTime(total);
      });
      scrubber.addEventListener("change", () => {
        audio.currentTime = Number(scrubber.value);
        isScrubbing = false;
        updateSyncUI();
      });
      audio.addEventListener("play", () => { btnPlay.textContent = "❚❚ 一時停止"; });
      audio.addEventListener("pause", () => { btnPlay.textContent = "▶ 対談を再生"; });
      audio.addEventListener("ended", () => { btnPlay.textContent = "▶ もう一度再生"; });
      audio.addEventListener("timeupdate", updateSyncUI);
      audio.addEventListener("loadedmetadata", updateSyncUI);
    })();
  </script>
</body>
</html>
""")


def _build_voice_rows_html(
    characters: dict[str, Any],
    themes: dict[str, Any],
    neon_voice: str,
) -> str:
    rows: list[str] = []
    koharu = characters["hosts"]["koharu"]
    heizo = characters["hosts"]["heizo"]

    rows.append(
        f"<tr><td><strong>{html.escape(koharu['name'])}</strong></td>"
        f"<td>メインパーソナリティ</td>"
        f"<td><code>{html.escape(koharu['tts']['gemini_voice'])}</code></td>"
        f"<td>pan {koharu['tts']['pan']:+.2f}（やや左）／明るく活発</td></tr>"
    )
    rows.append(
        f"<tr><td><strong>{html.escape(heizo['name'])}</strong></td>"
        f"<td>パートナーキャスター</td>"
        f"<td><code>{html.escape(heizo['tts']['gemini_voice'])}</code></td>"
        f"<td>pan {heizo['tts']['pan']:+.2f}（やや右）／優しく丁寧</td></tr>"
    )
    rows.append(
        f"<tr><td><strong>ネオン</strong>（特別回）</td>"
        f"<td>AIオーケストレーター</td>"
        f"<td><code>{html.escape(neon_voice)}</code></td>"
        f"<td>pan +0.00（中央）／知的で親しみやすい</td></tr>"
    )
    for day_cfg in themes.get("days", {}).values():
        g = day_cfg["guest"]
        rows.append(
            f"<tr><td><strong>{html.escape(g['name'])}</strong>（{html.escape(day_cfg['weekday_ja'])}）</td>"
            f"<td>{html.escape(day_cfg['theme_name'])}</td>"
            f"<td><code>{html.escape(g['voice_name'])}</code></td>"
            f"<td>pan +0.00（中央）／曜日別専門家ゲスト</td></tr>"
        )
    return "\n              ".join(rows)


def render_tech_page(
    tech_bundle: dict[str, Any] | None,
    characters: dict[str, Any],
    themes: dict[str, Any],
    common_css: str,
    nav_html: str,
    safe_json_fn: Any,
) -> str:
    """Render docs/tech.html with embedded Neon-san dialogue player and 6 SVG architecture diagrams."""
    if tech_bundle:
        ep = tech_bundle["episode"]
        mf = tech_bundle["manifest"]
        meta = ep["meta"]
        mf_meta = mf["meta"]
        neon_voice = (
            meta.get("voices", {}).get("guest", {}).get("gemini_voice")
            or ep.get("guest", {}).get("voice_name")
            or "Rasalgethi"
        )
        dur_fmt = mf_meta.get("total_duration_formatted", "15:00")
        dur_sec = mf_meta.get("total_duration_sec", 900)
        dur_hint = f"収録時間 {dur_fmt}" + ("（予定）" if mf_meta.get("estimated") else " ／ 小春×平蔵×ネオン")
        payload = {
            "has_audio": tech_bundle["has_audio"],
            "audio_src": f"audio/{meta['output_filename']}",
            "total_duration_sec": dur_sec,
            "total_duration_formatted": dur_fmt,
            "segments": mf["segments"],
        }
    else:
        neon_voice = "Rasalgethi"
        dur_fmt = "15:00"
        dur_hint = "音声準備中"
        payload = {
            "has_audio": False,
            "audio_src": "audio/kodaira_radio_tech_talk_neon.mp3",
            "total_duration_sec": 900,
            "total_duration_formatted": "15:00",
            "segments": [],
        }

    return TECH_HTML_TEMPLATE.substitute(
        COMMON_CSS=common_css,
        TECH_CSS=TECH_CSS,
        NAV_HTML=nav_html,
        TECH_DUR_HINT=html.escape(dur_hint),
        TECH_DUR_FMT=html.escape(dur_fmt),
        SVG_DIAGRAM_1=SVG_DIAGRAM_1,
        SVG_DIAGRAM_2=SVG_DIAGRAM_2,
        SVG_DIAGRAM_3=SVG_DIAGRAM_3,
        SVG_DIAGRAM_4=SVG_DIAGRAM_4,
        SVG_DIAGRAM_5=SVG_DIAGRAM_5,
        SVG_DIAGRAM_6=SVG_DIAGRAM_6,
        VOICE_ROWS_HTML=_build_voice_rows_html(characters, themes, neon_voice),
        PAYLOAD_JSON=safe_json_fn(payload),
    )
