"""Local Antigravity automation helper: prepares briefings, validates drafts, runs TTS/site build, and pushes."""

from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlencode, urlsplit, urlunsplit
import urllib.request

from build_site import ROOT_DIR as _SITE_ROOT  # noqa: F401
from generate_episode import (
    CONFIG_DIR,
    DATA_DIR,
    EPISODES_DIR,
    JST,
    RECENT_LOCAL_DEDUP_DAYS,
    EXPERT_HISTORY_DAYS,
    _apply_breaking_extension,
    _assemble_and_validate_episode,
    _detect_live_quake_special,
    _format_editorial_guide_block,
    _format_program_schedule_block,
    _load_json,
    _next_episode_number,
    _update_knowledge_log,
    _update_topic_history,
    build_dedup_context,
)
from live_feeds import collect_live_briefing
from kodaira_spots import (
    SPOT_COOLDOWN_DAYS,
    audit_plan_spot_overlaps,
    compute_spot_usage,
    format_spot_candidates_block,
    format_spot_cooldown_block,
    load_kodaira_spots,
    match_spots_in_text,
    select_balanced_spot_candidates,
)
from plan_weekly_editorial import (
    EDITORIAL_PLAN_PATH,
    _build_week_skeleton,
    _default_next_monday,
    _format_recent_history,
    _normalize_editorial_plan,
    merge_editorial_plans,
)
from schedule_calendar import resolve_day_plan, resolve_tomorrow_preview
from site_share import (
    DEFAULT_HERO_ALT,
    IMAGE_EXTS,
    load_weekly_banners,
    read_image_dimensions,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT_DIR / ".cache"
DOCS_AUDIO_DIR = ROOT_DIR / "docs" / "audio"
WEEKLY_BANNERS_PATH = DATA_DIR / "weekly_banners.json"
DOCS_WEEKLY_DIR = ROOT_DIR / "docs" / "assets" / "weekly"
CAST_REF_SHEET_PATH = ROOT_DIR / "docs" / "assets" / "hero_cast_banner.jpg"
WEEKLY_BANNER_CACHE_DIR = CACHE_DIR / "weekly_banners"
WIKIMEDIA_USER_AGENT = (
    "KodairaBousaiRadioBannerBot/1.0 "
    "(https://takahashikatsunori.github.io/kb-radio/; local editorial research)"
)
WIKIMEDIA_API_URL = "https://commons.wikimedia.org/w/api.php"
EXPRESSIVE_TAGS = ("<laugh>", "<chuckle>", "<giggle>", "<short pause>", "<breath>", "<sigh>")
STAGE_DIRECTION_PATTERNS = (
    re.compile(r"（[^）]*笑："),
    re.compile(r"【[^】]*】"),
)


def _find_git_exe() -> str:
    """Locate git.exe on PATH, GitHub Desktop's highest versioned app directory, or Program Files."""
    on_path = shutil.which("git")
    if on_path:
        return on_path

    local_app = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    gh_root = Path(local_app) / "GitHubDesktop"
    if gh_root.exists():
        versioned: list[tuple[tuple[int, ...], Path]] = []
        for app_dir in gh_root.glob("app-*"):
            m = re.fullmatch(r"app-(\d+(?:\.\d+)*)", app_dir.name)
            cand = app_dir / "resources" / "app" / "git" / "cmd" / "git.exe"
            if m and cand.exists():
                ver = tuple(int(p) for p in m.group(1).split("."))
                versioned.append((ver, cand))
        if versioned:
            versioned.sort(key=lambda item: item[0], reverse=True)
            return str(versioned[0][1])

    for fallback in (
        Path(r"C:\Program Files\Git\cmd\git.exe"),
        Path(r"C:\Program Files (x86)\Git\cmd\git.exe"),
    ):
        if fallback.exists():
            return str(fallback)

    raise FileNotFoundError("Could not find git.exe on PATH, GitHub Desktop, or Program Files.")


def _run_git(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run git non-interactively in ROOT_DIR."""
    git_exe = _find_git_exe()
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    res = subprocess.run(
        [git_exe, *args],
        cwd=str(ROOT_DIR),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and res.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (rc={res.returncode}):\n{res.stdout}\n{res.stderr}".strip()
        )
    return res


def _run_python_script(script_name: str, args: list[str]) -> None:
    """Execute a sibling script inside src/ with UTF-8 output enabled."""
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    cmd = [sys.executable, str(ROOT_DIR / "src" / script_name), *args]
    res = subprocess.run(cmd, cwd=str(ROOT_DIR), env=env)
    if res.returncode != 0:
        raise RuntimeError(f"{script_name} failed with exit code {res.returncode}")


def _load_optional_json(path: Path, default: Any) -> Any:
    return _load_json(path) if path.exists() else default


def _build_local_daily_prompt_md(
    target_date: str,
    ep_num: int,
    characters: dict[str, Any],
    day_plan: dict[str, Any],
    special_meta: dict[str, Any] | None,
    tomorrow_preview: dict[str, Any],
    knowledge_entries: list[dict[str, Any]],
    live_bundle: dict[str, Any],
    dedup_ctx: dict[str, Any],
) -> str:
    """Render concise self-contained prompt & schema instructions for local Antigravity drafting."""
    day_cfg = day_plan["day_cfg"]
    guest = day_cfg["guest"]
    koharu = characters["hosts"]["koharu"]
    heizo = characters["hosts"]["heizo"]
    year_num = int(target_date[:4])
    reiwa_num = year_num - 2018

    schedule_block = _format_program_schedule_block(day_plan)
    editorial_block = _format_editorial_guide_block(day_plan)
    recent_logs = json.dumps(knowledge_entries[-7:], ensure_ascii=False, indent=2)
    weather_json = json.dumps(live_bundle["weather"], ensure_ascii=False)
    quakes_json = json.dumps(live_bundle["earthquakes"][:5], ensure_ascii=False)
    links_json = json.dumps(live_bundle["verified_links"], ensure_ascii=False, indent=2)

    if special_meta:
        seg_ids_line = (
            '6コーナー固定 (`opening`, `kodaira_life`, `guest_talk`, `special_feature`, `daily_bousai`, `ending`)\n'
            f"- 特別コーナー: **{special_meta['title']}**（{special_meta['phase_label']}）: {special_meta['focus']}\n"
            '- `special_feature` の `bgm` は `"bgm_feature"`, `intro_jingle` は `"stinger"`, `outro_jingle` は `null`'
        )
    else:
        seg_ids_line = (
            '5コーナー固定 (`opening`, `kodaira_life`, `guest_talk`, `daily_bousai`, `ending`)'
        )

    return f"""# ローカル台本生成ブリーフィング：{target_date}（{day_plan['weekday_ja']}・第{ep_num}回）

## 番組スペック・必須制約
- **放送日**: {target_date}（{day_plan['weekday_ja']} / {year_num}年・令和{reiwa_num}年） / 第{ep_num}回
- **編成**: {day_plan['edition_label']}（目標 {round(day_plan['target_duration_sec'] / 60)}分）
- **文字数ターゲット**: 全セリフ `text` 合計 **{day_plan['min_chars']}〜{day_plan['max_chars']}文字（目標 {day_plan['target_chars']}文字）**
- **セグメント構成**: {seg_ids_line}
- **明日の予告（`ending` で必ず触れる）**: {tomorrow_preview['preview_hint']}

## 登場人物（`speaker` は `koharu`, `heizo`, `guest` のみ）
- `koharu`（小春）: {koharu['personality']}
- `heizo`（平蔵）: {heizo['personality']}
- `guest`（{guest['name']} / {guest['title']}）: {guest['personality']} 小平とのつながり: {guest['kodaira_connection']}
- **未解説キーワード優先候補（2〜4個を解説）**: {', '.join(dedup_ctx['fresh_keywords'][:6])}

{schedule_block}

{editorial_block}

## 重複禁止ルール
### ① 直近{RECENT_LOCAL_DEDUP_DAYS}日間の小平ローカル話題
{dedup_ctx['recent_local_text']}

### ①-B 小平スポット90日クールダウン対象（原則{SPOT_COOLDOWN_DAYS}日間は再登場NG／大型リニューアル・当日大イベントのみ例外）
{dedup_ctx.get('spot_cooldown_text', '（なし）')}

### ② 未紹介・季節適合スポット候補（当日の鮮度・最新ニュースに応じて臨機応変に差し替え可）
{dedup_ctx.get('spot_candidates_text', '（なし）')}

### ③ {guest['name']} 過去{EXPERT_HISTORY_DAYS}日間の既出キーワード
既出: {', '.join(dedup_ctx['expert_covered_keywords']) or 'なし'}
{dedup_ctx['expert_history_text']}

## 直近の学びログ（連続成長ストーリー用）
{recent_logs}

## ライブ気象・地震・検証済み基本リンク
- 気象: {weather_json}
- 地震: {quakes_json}
- 公式リンク候補:
{links_json}

## Web検索リサーチ＆ファクトチェックの厳守事項
1. **開催年・休館日の厳密確認**: 必ず {year_num}年（令和{reiwa_num}年）の公式日程・開館状況を確認し、前年以前の予定を混ぜないこと。特に**「月曜祝日の翌日（振替休館）」や曜日定休日**を必ず確認する。
2. **事実厳守**: 小春が素朴に予想・疑問を投げた直後は、平蔵またはゲストが必ず優しく補足・訂正して誤認を残さない。数値・制度・電話番号・URLは裏取りしたものだけを使う。
3. **`tts_text` ルール（超重要）**:
   - **通常の漢字・カタカナはそのまま残すこと（全文をひらがなにしないこと）**。
   - 難読の小平地名（小平市=こだいら市（文頭等で「こだまし」と誤読されやすいため）、小川町=おがわちょう、上水本町=じょうすいほんちょう、津田町=つだまち、御幸町=みゆきちょう、大沼町=おおぬまちょう、鷹の台=たかのだい、狭山・境緑道=さやま・さかいりょくどう 等）や、読み間違いやすい人名・施設名・英略語（平櫛田中彫刻美術館=ひらくし・でんちゅう・ちょうこくびじゅつかん（半角スペース+漢字「彫刻」で「ひらくしちゅうぞう」と誤読されやすいため）、XRAIN=エックスレイン、GPS=ジーピーエス 等）だけをかな／カタカナに開く。
   - `text` には `<...>` タグを絶対に入れない。`tts_text` には `<laugh>`, `<chuckle>`, `<giggle>`, `<short pause>`, `<breath>`, `<sigh>` を会話に合わせて豊富に入れる（合計20個以上目安）。
   - ト書き（「明るく笑って：」や `【...】`）は `tts_text` に書かない。
4. **出力先**:
   `.cache/local_daily_draft_{target_date}.json` に以下のJSONを書き出すこと。
   ```json
   {{
     "subtitle": "第{ep_num}回・{target_date}（{day_plan['weekday_ja']}）朝7時号 ― サブタイトル",
     "keywords_featured": ["解説した専門用語1", "専門用語2"],
     "kodaira_topics": ["話題1", "話題2"],
     "kodaira_areas": ["エリア1", "エリア2"],
     "links": [{{"category": "カテゴリ", "title": "タイトル", "url": "https://...", "note": "説明"}}],
     "references": [{{"category": "カテゴリ", "title": "見出し", "detail": "要点", "contact": "確認先"}}],
     "learned_notes": {{
       "learned_points": ["学び1", "学び2", "学び3"],
       "kodaira_discovery": "小平の魅力・暮らしと防災のつながり1文"
     }},
     "breaking_special": {{"has_breaking_special": false, "title": "", "summary": "", "extra_minutes": 0}},
     "fact_check": {{
       "status": "passed",
       "checked_claims_count": 20,
       "issues_found": 0,
       "patches_applied": 0,
       "summary": "裏取り監査の総評",
       "issues": []
     }},
     "segments": [
       {{
         "id": "opening",
         "title": "コーナータイトル",
         "bgm": "bgm_warm",
         "intro_jingle": "opening_jingle",
         "outro_jingle": null,
         "lines": [
           {{
             "speaker": "koharu",
             "text": "画面表示用テキスト（タグなし）",
             "tts_text": "読み上げ用テキスト（漢字維持＋難読のみかな＋<laugh>等）",
             "style": "bright, energetic, smiling",
             "pause_after": 0.32
           }}
         ]
       }}
     ]
   }}
   ```
"""


def _merge_breaking_special_from_draft(
    raw_draft: dict[str, Any],
    live_quake_special: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Merge optional draft breaking_special dict with deterministic live_quake_special."""
    parsed_special: dict[str, Any] | None = None
    bs = raw_draft.get("breaking_special")
    if isinstance(bs, dict) and bs.get("has_breaking_special") and str(bs.get("title") or "").strip():
        extra_min = max(3, min(5, int(bs.get("extra_minutes") or 3)))
        parsed_special = {
            "title": str(bs["title"]).strip(),
            "summary": str(bs.get("summary") or "").strip(),
            "extra_minutes": extra_min,
        }

    if live_quake_special and not parsed_special:
        return live_quake_special
    if live_quake_special and parsed_special:
        return {
            "title": parsed_special["title"],
            "summary": f"{live_quake_special['summary']} ／ {parsed_special['summary']}",
            "extra_minutes": max(parsed_special["extra_minutes"], live_quake_special["extra_minutes"]),
        }
    return parsed_special


def validate_daily_draft(
    raw_draft: dict[str, Any],
    final_plan: dict[str, Any],
    special_meta: dict[str, Any] | None,
    allow_char_overflow: bool = False,
) -> dict[str, Any]:
    """Run strict pre-TTS quality and structural checks on a daily draft JSON."""
    errors: list[str] = []
    warnings: list[str] = []

    for req_key in ("subtitle", "segments", "learned_notes", "references", "links"):
        if req_key not in raw_draft or not raw_draft.get(req_key):
            errors.append(f"Missing or empty required top-level key: '{req_key}'")

    segments = raw_draft.get("segments") or []
    expected_ids = (
        ["opening", "kodaira_life", "guest_talk", "special_feature", "daily_bousai", "ending"]
        if special_meta
        else ["opening", "kodaira_life", "guest_talk", "daily_bousai", "ending"]
    )
    actual_ids = [str(s.get("id") or "") for s in segments if isinstance(s, dict)]
    if actual_ids != expected_ids:
        errors.append(f"Segment IDs mismatch: expected {expected_ids}, got {actual_ids}")

    display_chars = 0
    tts_texts: list[str] = []
    tag_count = 0
    for s_idx, seg in enumerate(segments):
        for l_idx, line in enumerate(seg.get("lines") or []):
            txt = str(line.get("text") or "")
            tts = str(line.get("tts_text") or "")
            display_chars += len(txt.strip())
            if re.search(r"<[^>]+>", txt):
                errors.append(f"Display text contains <...> tag at segment[{s_idx}].line[{l_idx}]")
            for pat in STAGE_DIRECTION_PATTERNS:
                if pat.search(tts):
                    errors.append(f"tts_text contains stage-direction pattern at segment[{s_idx}].line[{l_idx}]")
            tts_texts.append(tts)
            lower_tts = tts.lower()
            for tg in EXPRESSIVE_TAGS:
                tag_count += lower_tts.count(tg)

    min_chars = int(final_plan["min_chars"])
    max_chars = int(final_plan["max_chars"])
    hard_min = int(min_chars * 0.90)
    hard_max = int(max_chars * 1.08)
    if not allow_char_overflow and not (hard_min <= display_chars <= hard_max):
        errors.append(
            f"display_chars={display_chars} is outside hard bounds [{hard_min}, {hard_max}] "
            f"(target {min_chars}..{max_chars})"
        )
    elif not (min_chars <= display_chars <= max_chars):
        warnings.append(
            f"display_chars={display_chars} is slightly outside target [{min_chars}, {max_chars}]"
        )

    joined_tts = "\n".join(tts_texts)
    kanji_count = len(re.findall(r"[\u4e00-\u9fff]", joined_tts))
    kanji_ratio = kanji_count / max(1, len(joined_tts))
    if kanji_ratio < 0.10:
        errors.append(
            f"tts_text appears overly hiragana-converted (kanji ratio={kanji_ratio:.3f} < 0.10; "
            f"keep normal kanji and expand only hard place names/acronyms)"
        )

    if tag_count < 20:
        errors.append(f"Too few expressive inline tags in tts_text: {tag_count} (< 20)")

    for i, lk in enumerate(raw_draft.get("links") or []):
        url = str(lk.get("url") or "") if isinstance(lk, dict) else ""
        if not url.startswith("https://"):
            errors.append(f"Link[{i}] has invalid non-https URL: {url!r}")

    notes = raw_draft.get("learned_notes") or {}
    pts = notes.get("learned_points") or []
    if not isinstance(pts, list) or len(pts) < 2:
        errors.append("learned_notes.learned_points must contain at least 2 entries")
    if not str(notes.get("kodaira_discovery") or "").strip():
        errors.append("learned_notes.kodaira_discovery must be non-empty")

    if not isinstance(raw_draft.get("references"), list) or len(raw_draft["references"]) == 0:
        errors.append("references must be a non-empty list")

    if errors:
        raise ValueError("Daily draft failed validation:\n- " + "\n- ".join(errors))

    return {
        "display_chars": display_chars,
        "kanji_ratio": round(kanji_ratio, 4),
        "tag_count": tag_count,
        "warnings": warnings,
    }


def cmd_prepare_daily(args: argparse.Namespace) -> None:
    target_date = args.date or datetime.now(JST).strftime("%Y-%m-%d")
    datetime.strptime(target_date, "%Y-%m-%d")

    if not args.no_pull:
        _run_git(["pull", "--rebase"])

    ep_json_path = EPISODES_DIR / target_date / "episode.json"
    mp3_path = DOCS_AUDIO_DIR / f"kodaira_radio_{target_date.replace('-', '')}.mp3"
    if ep_json_path.exists() and mp3_path.exists() and mp3_path.stat().st_size > 1024:
        print(f"STATUS: ALREADY_BUILT ({target_date})")
        return
    if ep_json_path.exists():
        print(f"STATUS: SCRIPT_EXISTS_NEEDS_TTS ({target_date})")
        print(f"EPISODE_JSON: {ep_json_path}")
        return

    characters = _load_json(CONFIG_DIR / "characters.json")
    themes = _load_json(CONFIG_DIR / "weekly_themes.json")
    special_days = _load_optional_json(CONFIG_DIR / "special_days.json", {"recurring": [], "dated_events": []})
    program_schedule = _load_optional_json(CONFIG_DIR / "program_schedule.json", None)
    knowledge_data = _load_optional_json(DATA_DIR / "knowledge_log.json", {"entries": []})
    topic_history_data = _load_optional_json(DATA_DIR / "topic_history.json", {"entries": []})
    editorial_plan = _load_optional_json(DATA_DIR / "editorial_plan.json", None)

    day_plan = resolve_day_plan(
        target_date,
        themes,
        special_days,
        editorial_plan=editorial_plan,
        program_schedule=program_schedule,
    )
    tomorrow_preview = resolve_tomorrow_preview(
        target_date,
        themes,
        special_days,
        editorial_plan=editorial_plan,
        program_schedule=program_schedule,
    )
    ep_num = _next_episode_number(target_date)
    spots_cfg = load_kodaira_spots()
    dedup_ctx = build_dedup_context(
        target_date,
        day_plan,
        topic_history_data.get("entries", []),
        editorial_plan=editorial_plan,
        spots_cfg=spots_cfg,
    )
    live_bundle = collect_live_briefing()
    live_quake_special = _detect_live_quake_special(live_bundle["earthquakes"])
    effective_plan, special_meta = _apply_breaking_extension(day_plan, live_quake_special)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    briefing_path = CACHE_DIR / f"local_daily_briefing_{target_date}.json"
    prompt_path = CACHE_DIR / f"local_daily_prompt_{target_date}.md"
    draft_path = CACHE_DIR / f"local_daily_draft_{target_date}.json"

    briefing_payload = {
        "target_date": target_date,
        "episode_number": ep_num,
        "day_plan": day_plan,
        "effective_plan": effective_plan,
        "special_meta": special_meta,
        "tomorrow_preview": tomorrow_preview,
        "dedup_ctx": dedup_ctx,
        "live_bundle": live_bundle,
        "live_quake_special": live_quake_special,
        "recent_knowledge_log": (knowledge_data.get("entries") or [])[-7:],
    }
    briefing_path.write_text(json.dumps(briefing_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    prompt_md = _build_local_daily_prompt_md(
        target_date=target_date,
        ep_num=ep_num,
        characters=characters,
        day_plan=effective_plan,
        special_meta=special_meta,
        tomorrow_preview=tomorrow_preview,
        knowledge_entries=knowledge_data.get("entries", []),
        live_bundle=live_bundle,
        dedup_ctx=dedup_ctx,
    )
    prompt_path.write_text(prompt_md, encoding="utf-8")

    cur_w = (live_bundle.get("weather") or {}).get("current") or {}
    guest = effective_plan["day_cfg"]["guest"]
    print(f"STATUS: READY_FOR_SCRIPT ({target_date})")
    print(f"BRIEFING_JSON: {briefing_path}")
    print(f"PROMPT_MD: {prompt_path}")
    print(f"DRAFT_TARGET: {draft_path}")
    print(f"EDITION: {effective_plan['edition_label']} | Episode #{ep_num}")
    print(f"CHAR_BOUNDS: {effective_plan['min_chars']}..{effective_plan['max_chars']} (target {effective_plan['target_chars']})")
    print(f"GUEST: {guest['name']} ({effective_plan['day_cfg']['theme_name']})")
    print(f"SPECIAL: {special_meta['title'] if special_meta else 'None'}")
    print(f"WEATHER: {cur_w.get('weather')} / {cur_w.get('temperature_c')}C | QUAKES_48H: {len(live_bundle.get('earthquakes') or [])}")


def cmd_finalize_daily(args: argparse.Namespace) -> None:
    target_date = args.date or datetime.now(JST).strftime("%Y-%m-%d")
    datetime.strptime(target_date, "%Y-%m-%d")
    ep_dir = EPISODES_DIR / target_date
    ep_json_path = ep_dir / "episode.json"

    if not args.tts_only:
        draft_path = Path(args.draft) if args.draft else (CACHE_DIR / f"local_daily_draft_{target_date}.json")
        briefing_path = CACHE_DIR / f"local_daily_briefing_{target_date}.json"
        if not draft_path.exists():
            raise FileNotFoundError(f"Draft JSON not found: {draft_path}")
        if not briefing_path.exists():
            raise FileNotFoundError(f"Briefing JSON not found: {briefing_path}")

        raw_draft = _load_json(draft_path)
        briefing = _load_json(briefing_path)
        characters = _load_json(CONFIG_DIR / "characters.json")

        merged_breaking = _merge_breaking_special_from_draft(
            raw_draft, briefing.get("live_quake_special")
        )
        final_plan, special_meta = _apply_breaking_extension(briefing["day_plan"], merged_breaking)
        check_info = validate_daily_draft(
            raw_draft,
            final_plan,
            special_meta,
            allow_char_overflow=args.allow_char_overflow,
        )
        for w in check_info["warnings"]:
            print(f"WARNING: {w}")

        spots_cfg = load_kodaira_spots()
        draft_spot_ids = match_spots_in_text(
            "\n".join(
                [
                    str(raw_draft.get("subtitle") or ""),
                    *(str(t) for t in (raw_draft.get("kodaira_topics") or [])),
                    *(str(a) for a in (raw_draft.get("kodaira_areas") or [])),
                ]
            ),
            spots_cfg,
        )
        topic_entries = _load_optional_json(DATA_DIR / "topic_history.json", {"entries": []}).get("entries", [])
        usage_map = compute_spot_usage(
            spots_cfg,
            topic_entries,
            editorial_plan=_load_optional_json(EDITORIAL_PLAN_PATH, None),
            reference_date=target_date,
            exclude_date_range=(target_date, target_date),
        )
        for sid in draft_spot_ids:
            u = usage_map.get(sid) or {}
            if u.get("in_cooldown"):
                print(
                    f"WARNING: SPOT_OVERLAP {sid} appeared on {u.get('cooldown_trigger_dates')} "
                    f"(verify major renewal/event exception or freshness)."
                )

        episode = _assemble_and_validate_episode(
            raw_generated=raw_draft,
            target_date=target_date,
            ep_num=int(briefing["episode_number"]),
            characters=characters,
            day_plan=final_plan,
            special_meta=special_meta,
            tomorrow_preview=briefing["tomorrow_preview"],
            live_bundle=briefing["live_bundle"],
            fallback_links=briefing["live_bundle"]["verified_links"],
            research_model="antigravity-local",
            script_model="antigravity-local",
            factcheck_model="antigravity-local",
        )

        raw_fc = raw_draft.get("fact_check") if isinstance(raw_draft.get("fact_check"), dict) else {}
        raw_issues = [it for it in (raw_fc.get("issues") or []) if isinstance(it, dict)]
        episode["meta"]["fact_check"] = {
            "model": "antigravity-local",
            "status": str(raw_fc.get("status") or "passed"),
            "checked_claims_count": int(raw_fc.get("checked_claims_count") or 0),
            "issues_found": int(raw_fc.get("issues_found") if raw_fc.get("issues_found") is not None else len(raw_issues)),
            "patches_applied": int(raw_fc.get("patches_applied") or 0),
            "summary": str(raw_fc.get("summary") or "Verified locally by Antigravity web search audit.").strip(),
            "issues": raw_issues[:12],
        }

        ep_dir.mkdir(parents=True, exist_ok=True)
        ep_json_path.write_text(json.dumps(episode, ensure_ascii=False, indent=2), encoding="utf-8")
        _update_knowledge_log(episode)
        _update_topic_history(episode)
        print(
            f"Saved {ep_json_path} "
            f"(chars={check_info['display_chars']}, kanji_ratio={check_info['kanji_ratio']}, tags={check_info['tag_count']})"
        )
    elif not ep_json_path.exists():
        raise FileNotFoundError(f"--tts-only requested, but {ep_json_path} does not exist")

    if not args.no_tts:
        _run_python_script(
            "build_radio.py",
            [str(ep_json_path), "--tts-engine", "gemini", "--bitrate", "112k"],
        )

    _run_python_script("build_site.py", [])

    if args.push:
        _run_git(["add", "episodes/", "data/knowledge_log.json", "data/topic_history.json", "docs/"])
        status = _run_git(["status", "--porcelain"])
        if status.stdout.strip():
            _run_git(["commit", "-m", f"radio: broadcast {target_date}"])
            _run_git(["pull", "--rebase"])
            _run_git(["push"])
            print(f"Pushed broadcast {target_date} to origin/main.")
        else:
            print("No repository changes to commit.")

    print(f"STATUS: DAILY_COMPLETE ({target_date})")


SEASON_PROFILES: dict[int, dict[str, Any]] = {
    1: {
        "season_label": "真冬・お正月・松の内",
        "attire": "厚手の冬コート・ダウンジャケット、マフラー、手袋（防寒重視、スタジオ衣装から着替える）",
        "foliage": "冬晴れの澄んだ青空、ケヤキの落葉枝、シラカシ・マツ・ツバキ等の常緑樹",
        "atmosphere": "凛とした冬の光、湯気・温かい飲み物・正月飾りや梅のつぼみなど新春の暮らし",
    },
    2: {
        "season_label": "厳冬〜早春（梅の季節）",
        "attire": "厚手コートや中綿ジャケット、ニット帽・マフラー（寒さ対策の冬服）",
        "foliage": "冬枯れの並木道にほころぶ紅白の梅、常緑の雑木林、低い冬の陽光",
        "atmosphere": "澄んだ空気、節分〜立春、早春の陽だまりと防災備蓄点検",
    },
    3: {
        "season_label": "早春・卒業と桜前線",
        "attire": "春コート・トレンチコートやカーディガン＋軽めマフラー（月後半はマフラー外して軽快に）",
        "foliage": "芽吹き始めた木々、コブシ・サクラのつぼみ〜開花、菜の花",
        "atmosphere": "やわらかな春の光、新生活・通学路・桜通りのにぎわい",
    },
    4: {
        "season_label": "春本番・桜と新緑",
        "attire": "春ジャケット・シャツ・薄手カーディガン・春色スニーカー（厚手コートやマフラーは厳禁）",
        "foliage": "満開〜葉桜のソメイヨシノ、鮮やかな若葉、チューリップやツツジのつぼみ",
        "atmosphere": "うららかな春の日差し、花びら舞う玉川上水や公園散歩",
    },
    5: {
        "season_label": "初夏・新緑のグリーンロード",
        "attire": "長袖シャツ・薄手パーカー・半袖＋軽い羽織り（冬服・重アウター厳禁）",
        "foliage": "まぶしい新緑のトンネル（玉川上水・狭山・境緑道）、色鮮やかなツツジやサツキ",
        "atmosphere": "爽やかな初夏の風、木漏れ日、水辺やサイクリングロードの活気",
    },
    6: {
        "season_label": "梅雨・あじさいと水辺",
        "attire": "初夏の半袖・七分袖＋レインジャケットや傘・長靴等の雨具小物",
        "foliage": "青・紫・白のあじさい、雨に濡れて濃い緑を帯びた木々、蓮や菖蒲",
        "atmosphere": "しっとりした梅雨空・雨上がり・雲の合間の光（晴れに固定せず天候表現も歓迎）",
    },
    7: {
        "season_label": "盛夏・夏休みと夕涼み",
        "attire": "半袖Tシャツ・ポロシャツ・夏用ワンピース・麦わら帽子やキャップ・日傘（長袖コート厳禁）",
        "foliage": "濃い緑葉のケヤキ並木、ヒマワリ・アサガオ・百日紅（サルスベリ）",
        "atmosphere": "力強い夏の日差し・入道雲、または夕方の涼風・打ち水・夏休み",
    },
    8: {
        "season_label": "真夏・夏祭りと涼",
        "attire": "真夏の軽装（半袖・通気性の良い服・帽子・タオル、シーンに応じ浴衣や法被も可）",
        "foliage": "緑陰の雑木林、ヒマワリ、緑のカーテン（ゴーヤ・アサガオ）",
        "atmosphere": "青空と入道雲、夕方〜宵の提灯・夏祭り・クールスポット・水分補給",
    },
    9: {
        "season_label": "初秋・防災の日とコスモス",
        "attire": "七分袖・長袖シャツ・薄手ベストや軽カーディガン（秋口の動きやすい服装）",
        "foliage": "少し色づき始めた葉、ヒガンバナ（曼珠沙華）、キキョウやコスモス、青空のうろこ雲",
        "atmosphere": "爽やかな秋風、防災訓練や農作物・夕暮れの散歩道",
    },
    10: {
        "season_label": "秋晴れ・実りと紅葉始まり",
        "attire": "秋ジャケット・ベスト・ニットカーディガン・動きやすいスニーカー",
        "foliage": "黄色・橙色に色づき始めたイチョウ・ケヤキ、柿やキウイ等の実り、秋の花",
        "atmosphere": "高い秋空、気持ちの良い散歩・収穫祭・地域イベント",
    },
    11: {
        "season_label": "晩秋・紅葉最盛期",
        "attire": "トレンチコート・セーター・ライトダウン・薄手マフラーなどの晩秋コーディネート",
        "foliage": "赤・黄・橙のモミジ・イチョウ・ケヤキ紅葉と落ち葉のじゅうたん",
        "atmosphere": "柔らかな斜光・澄んだ空気・焼き芋や旬のキウイ・紅葉ライトアップ等",
    },
    12: {
        "season_label": "初冬〜師走・クリスマス＆大晦日",
        "attire": "冬コート・ダッフルコート・ニット・マフラー・手袋（12月前半は軽め冬服、後半はしっかり防寒）",
        "foliage": "終盤の落ち葉〜冬木立、シラカシ等の常緑樹、クリスマス飾りや年末の正月準備",
        "atmosphere": "澄んだ冬の空気、昼の陽だまりからイルミネーション・大晦日の静かな境内まで自在",
    },
}


def _describe_season_context(start_dt: date, end_dt: date) -> dict[str, Any]:
    """Return season-accurate attire, foliage, atmosphere, and date-specific alerts for the week."""
    mid_dt = start_dt + (end_dt - start_dt) // 2
    profile = dict(SEASON_PROFILES[mid_dt.month])
    special_notes: list[str] = []

    span_days = (end_dt - start_dt).days + 1
    dates_in_week = [start_dt + timedelta(days=i) for i in range(span_days)]
    mmdd_set = {(d.month, d.day) for d in dates_in_week}

    if any((12, d) in mmdd_set for d in range(20, 26)):
        special_notes.append("クリスマス期：街のツリー・リースや赤レンガの冬景色などが映える時期（服装は冬服）。")
    if any((12, d) in mmdd_set for d in range(27, 31)) or (12, 31) in mmdd_set or any((1, d) in mmdd_set for d in range(1, 6)):
        special_notes.append(
            "年末年始（12/27〜1/5）注意：小平ふるさと村等の多くの市立文化施設が休園・休館するため、年末・年始の営業／開門状況を必ず検索確認すること（神社境内や駅前広場・公園など年末年始も開いている場を選定）。"
        )
    if any((3, d) in mmdd_set for d in range(24, 32)) or any((4, d) in mmdd_set for d in range(1, 10)):
        special_notes.append("桜シーズン：都道や玉川上水・小平霊園・たけのこ公園等のソメイヨシノ開花状況を確認。")
    if (9, 1) in mmdd_set:
        special_notes.append("防災の日（9/1）週：地域防災・起震車・公園防災施設等との連動が好適。")

    profile["month"] = mid_dt.month
    profile["week_range"] = f"{start_dt.isoformat()}〜{end_dt.isoformat()}"
    profile["special_notes"] = special_notes
    profile["time_of_day_policy"] = "時間帯は朝7時固定にせず、そのスポットと季節の魅力が最も映える昼・夕方・灯りの時間帯を自由に選んでよい。"
    return profile


def _has_weekly_banner(week_start: str) -> bool:
    """Return True if a valid banner image already exists for week_start."""
    data = load_weekly_banners(WEEKLY_BANNERS_PATH)
    if data:
        for entry in data.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("week_start") or "").strip() == week_start:
                rel = str(entry.get("rel_path") or entry.get("banner_path") or "").strip()
                if rel:
                    cand = ROOT_DIR / "docs" / rel.lstrip("/")
                    if cand.is_file() and cand.stat().st_size > 512:
                        return True
    for ext in IMAGE_EXTS:
        cand = DOCS_WEEKLY_DIR / f"{week_start}{ext}"
        if cand.is_file() and cand.stat().st_size > 512:
            return True
    return False


def _recent_banner_spots_summary(limit: int = 8) -> str:
    data = load_weekly_banners(WEEKLY_BANNERS_PATH)
    entries = (data or {}).get("entries") or []
    lines: list[str] = []
    for e in entries[-limit:]:
        if not isinstance(e, dict):
            continue
        ws = str(e.get("week_start") or "")
        spot = str(e.get("spot_name") or "").strip()
        season = str(e.get("season_label") or "").strip()
        if spot:
            lines.append(f"- {ws}: {spot}（{season}）")
    return "\n".join(lines) if lines else "- なし（今回が初回シーズンバナー作成）"


def _build_weekly_banner_guide_md(
    start_dt: date,
    end_dt: date,
    week_arc: dict[str, Any],
    daily_guides: list[dict[str, Any]],
    past_banners_summary: str,
) -> str:
    """Build actionable Photo-Anchored 5-Rule 3-Pattern Banner Protocol instructions for the target week."""
    season_ctx = _describe_season_context(start_dt, end_dt)
    start_str = start_dt.isoformat()
    end_str = end_dt.isoformat()
    cache_dir = WEEKLY_BANNER_CACHE_DIR / start_str
    meta_target = cache_dir / "banner_meta.json"
    proposals_target = cache_dir / "proposals.md"

    daily_lines: list[str] = []
    for g in daily_guides:
        if not isinstance(g, dict):
            continue
        daily_lines.append(
            f"- {g.get('date')}（{g.get('weekday_ja', '')}）: {g.get('focus_area', '')} / {g.get('kodaira_angle', '')}"
        )
    daily_block = "\n".join(daily_lines) if daily_lines else "- （週間ガイド作成中に決定する7日間の重点エリアに連動）"
    special_notes_block = (
        "\n".join(f"- ⚠️ {n}" for n in season_ctx["special_notes"])
        if season_ctx["special_notes"]
        else "- 特段の長期一斉休館期間なし（ただし各スポットの曜定休日・月曜祝日の翌日休館は必ずWeb確認）"
    )

    return f"""# 週次タイトルバナー制作ガイド：{start_str} 〜 {end_str}

## 対象週のテーマ・季節コンテキスト
- **週間キャッチタイトル**: {week_arc.get('title', '未設定（これから作成）')}
- **週間コンセプト**: {week_arc.get('concept', '')}
- **季節プロファイル（{season_ctx['month']}月）**: {season_ctx['season_label']}
- **服装ルール（厳守・毎週季節適応）**: **{season_ctx['attire']}**
  ※ 冬服固定は厳禁！基準キャスト画像（`hero_cast_banner.jpg`）のスタジオ服をそのまま使わず、上記対象週の季節・気候に自然になじむ衣装へ着替えさせること。
- **植生・背景雰囲気**: {season_ctx['foliage']} ／ {season_ctx['atmosphere']}
- **時間帯ポリシー**: {season_ctx['time_of_day_policy']}
- **季節・開館注意事項**:
{special_notes_block}

## 対象週の日別注目エリア・ネタ
{daily_block}

## 直近使用済みスポット（重複回避・多様な小平の名所を優先）
{past_banners_summary}

---

## Photo-Anchored 5-Rule 3-Pattern Banner Protocol（必ず全5ルールを実行）

### Rule 1: 実在スポット3か所の調査と選定（A・B・C）
- 今週のテーマと季節に合う **東京都小平市内の実在スポットを3パターン（A・B・C）** 選ぶ（`config/kodaira_spots.json` の16ジャンルを参照し、駅・公園・社寺・博物館/植物園・工場/企業・商店会・カフェ・緑道・農業スポット等をバランスよく、直近バナーと非重複に選定）。
- `search_web` で各スポットの **{start_str}〜{end_str} 期間中の実際の開館・開園状況、建造物の実寸サイズ感、周辺景観** を必ず裏取りする（例：休館中・工事中の施設ににぎわう観客を描かない、高さ約2.8mの丸ポストを小柄な高さに縮めない等）。

### Rule 2: 実写写真（Wide + Detail）の取得と目視確認
- `fetch-banner-refs` コマンドで Wikimedia Commons 検索（`--commons-search`）および画像ダウンロード（`--download`）を実行し、各スポットごとに **建物全景がわかる引き写真（`anchor_wide`）1枚** と **質感や細部がわかる寄り写真（`detail`）1枚** を取得する（必要に応じ小平市公式ページ等の verified 画像も可）。
  ```powershell
  c:\\Users\\katsunori\\Documents\\GitHub\\kb-radio\\.venv\\Scripts\\python.exe c:\\Users\\katsunori\\Documents\\GitHub\\kb-radio\\src\\local_automation.py fetch-banner-refs --week-start {start_str} --commons-search "検索語1" --commons-search "検索語2"
  c:\\Users\\katsunori\\Documents\\GitHub\\kb-radio\\.venv\\Scripts\\python.exe c:\\Users\\katsunori\\Documents\\GitHub\\kb-radio\\src\\local_automation.py fetch-banner-refs --week-start {start_str} --download a_wide="File:..." --download a_detail="File:..."
  ```
- **必須ゲート**: `extmetadata` で **東京都小平市**（他県・北海道等の同名施設でないこと）を確認し、さらに **取得した全画像を `read_file` で目視確認** してから次へ進む。

### Rule 3: 厳密3枚参照（`image-generator`）によるA・B・C生成
- 各パターンにつき `image-generator` サブエージェントへ渡す参照画像は **必ず次の3枚ちょうど（上限厳守）**:
  1. `{CAST_REF_SHEET_PATH}`（9人基準キャラクター参照シート — 絶対に改変・上書きしない）
  2. `<pattern>_wide`（実写アンカー全景写真 — カメラアングル・屋根勾配・柱・外壁素材・周辺樹木を忠実に維持）
  3. `<pattern>_detail`（実写ディテール写真 — 装飾・質感・象徴物のディテール根拠）
- プロンプト必須要素:
  - **アスペクト比 16:9（1376×768）**、温かみのあるアニメ・イラスト調。
  - **主役は小春（約160cm）＆平蔵（約175cm）**: 手前〜中景でそのスポットと週テーマを楽しむアクティブなポーズ・生き生きとした表情。
  - **専門家は脇役（2〜3名）**: その週の重点曜日の専門家を中景〜背景に自然に配置（**人物の重複登場禁止・計4〜5名程度まで**）。
  - **実寸スケールの厳守**: 建造物・ポスト・鳥居・門・樹木の実際の高さに対して、身長160〜175cmの人間が不自然に大きくならないよう厳密に指定。
  - **季節適応衣装**: 基準シートのスタジオ衣装ではなく、**{season_ctx['attire']}** を明確に指示。
  - **文字崩れゼロ**: 小さな看板文字・扁額・絵馬等の読めない擬似漢字は省くか無地／簡素化する（`kb-radio` 等の不自然な英字ロゴも入れない）。

### Rule 4: 5軸サイドバイサイドQC（必ず実写と並べて目視判定）
生成された各パターン画像を **`anchor_wide` 実写写真と並べて `read_file` で比較検査** し、以下5軸で 0〜10点評価・検品する（不具合があるパターンのみ **最大1回まで** リテイクし、クォータ浪費を防ぐ）：
1. **建築・ランドマーク再現度**: 実写の屋根・柱・窓・外壁材・境内や公園配置と大きく食い違っていないか
2. **人体・建造物の実寸スケール**: 160cm小春・175cm平蔵の身長が建造物サイズに対してリアルか
3. **キャスト同一性＆主従バランス**: 小春・平蔵が主役、専門家2〜3名が脇役、顔や衣装の破綻・人物重複がないか
4. **季節感・開館整合性**: {season_ctx['month']}月（{season_ctx['season_label']}）にふさわしい服装・植生で、休館日表現に矛盾がないか
5. **文字崩れゼロ**: 看板・おみくじ・掲示板に不自然な崩れ漢字が紛れ込んでいないか

### Rule 5: メタデータ保存・自動選定＆バックナンバー永久アーカイブ
1. 以下スキーマで `{meta_target}` を書き出し、A/B/C比較解説を `{proposals_target}` にまとめる（全3候補の画像を永久保存するため、3パターンすべての `source_path` を記載すること）:
```json
{{
  "week_start": "{start_str}",
  "week_end": "{end_str}",
  "selected_pattern": "最も5軸QC評価が高いパターン記号 (A|B|C)",
  "selection_mode": "auto",
  "candidates": [
    {{
      "pattern": "A",
      "spot_name": "小平市内スポット名",
      "season_label": "{season_ctx['season_label']}",
      "caption": "{start_str}週｜スポット名（季節のひとこと）",
      "alt": "小春・平蔵と専門家ゲストが○○を楽しむ番組バナーイラスト",
      "source_path": "image-generatorが保存したJPEGの絶対パス",
      "wide_ref": "a_wideの絶対パス",
      "detail_ref": "a_detailの絶対パス",
      "qc_score": 9.2,
      "qc_notes": "5軸QCの所見"
    }}
  ]
}}
```
2. 登録・サイト再ビルド・公開:
   - **週間編成も同時作成する場合 (`READY_FOR_WEEKLY_PLAN`)**:
     `finalize-weekly --start-date {start_str} --draft <draft_json> --banner-meta {meta_target} --push`
   - **バナーのみ作成する場合 (`READY_FOR_BANNER_ONLY`)**:
     `set-weekly-banner --meta-json {meta_target} --push`
3. 完了報告では **A・B・C全3パターン（スポット名・QC評価・画像パス）** と **自動採用したパターン** を明記し、「別パターンへの切替をご希望の場合は `A` / `B` / `C` のいずれかをご指定ください」と添える。
"""


def _strip_html_text(raw: str, limit: int = 240) -> str:
    txt = html_lib.unescape(raw or "")
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    if limit > 0 and len(txt) > limit:
        return txt[: limit - 1].rstrip() + "…"
    return txt


def _encode_url(raw_url: str) -> str:
    parts = urlsplit(raw_url.strip())
    safe_path = quote(unquote(parts.path), safe="/:@!$&'()*+,;=-._~")
    return urlunsplit((parts.scheme, parts.netloc, safe_path, parts.query, parts.fragment))


def _commons_api_json(params: dict[str, Any]) -> dict[str, Any]:
    q = dict(params)
    q["format"] = "json"
    url = f"{WIKIMEDIA_API_URL}?{urlencode(q)}"
    req = urllib.request.Request(url, headers={"User-Agent": WIKIMEDIA_USER_AGENT})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _resolve_download_url(target: str) -> str:
    cleaned = target.strip()
    file_title = ""
    if cleaned.startswith("File:") or cleaned.startswith("ファイル:"):
        file_title = "File:" + cleaned.split(":", 1)[1].strip()
    elif "commons.wikimedia.org/wiki/File:" in cleaned:
        after = cleaned.split("/wiki/", 1)[1].split("?", 1)[0].split("#", 1)[0]
        file_title = unquote(after)
    if file_title:
        data = _commons_api_json(
            {
                "action": "query",
                "titles": file_title,
                "prop": "imageinfo",
                "iiprop": "url|size|mime",
                "iiurlwidth": 1600,
            }
        )
        pages = (data.get("query") or {}).get("pages") or {}
        for page in pages.values():
            infos = page.get("imageinfo") or []
            if infos:
                info = infos[0]
                chosen = info.get("thumburl") or info.get("url")
                if chosen:
                    return str(chosen)
        raise FileNotFoundError(f"Wikimedia Commons file not found: {file_title}")
    return _encode_url(cleaned)


def _guess_image_ext(url: str, content_type: str = "") -> str:
    ct = content_type.split(";", 1)[0].strip().lower()
    ct_map = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }
    if ct in ct_map:
        return ct_map[ct]
    suffix = Path(urlsplit(url).path).suffix.lower()
    if suffix == ".jpeg":
        return ".jpg"
    if suffix in (".jpg", ".png", ".webp"):
        return suffix
    return ".jpg"


def cmd_fetch_banner_refs(args: argparse.Namespace) -> None:
    week_start = str(args.week_start or "").strip()
    datetime.strptime(week_start, "%Y-%m-%d")

    searches = [str(s).strip() for s in (args.commons_search or []) if str(s).strip()]
    downloads = [str(d).strip() for d in (args.download or []) if str(d).strip()]
    if not searches and not downloads:
        raise ValueError("Provide at least one --commons-search QUERY or --download LABEL=URL_OR_FILE.")

    output: dict[str, Any] = {
        "week_start": week_start,
        "commons_results": {},
        "downloaded": [],
    }

    for query in searches:
        data = _commons_api_json(
            {
                "action": "query",
                "generator": "search",
                "gsrnamespace": 6,
                "gsrlimit": 8,
                "gsrsearch": query,
                "prop": "imageinfo",
                "iiprop": "url|size|mime|extmetadata",
                "iiurlwidth": 1400,
            }
        )
        pages = (data.get("query") or {}).get("pages") or {}
        rows: list[dict[str, Any]] = []
        for page in sorted(pages.values(), key=lambda p: p.get("index", 999)):
            infos = page.get("imageinfo") or []
            if not infos:
                continue
            info = infos[0]
            mime = str(info.get("mime") or "")
            if not mime.startswith("image/") or mime == "image/svg+xml":
                continue
            meta = info.get("extmetadata") or {}
            rows.append(
                {
                    "title": page.get("title", ""),
                    "width": info.get("width"),
                    "height": info.get("height"),
                    "mime": mime,
                    "thumburl": info.get("thumburl") or "",
                    "url": info.get("url") or "",
                    "description": _strip_html_text((meta.get("ImageDescription") or {}).get("value", "")),
                    "categories": _strip_html_text((meta.get("Categories") or {}).get("value", ""), limit=200),
                    "artist": _strip_html_text((meta.get("Artist") or {}).get("value", ""), limit=120),
                    "license": _strip_html_text((meta.get("LicenseShortName") or {}).get("value", ""), limit=80),
                }
            )
        output["commons_results"][query] = rows

    if downloads:
        refs_dir = WEEKLY_BANNER_CACHE_DIR / week_start / "refs"
        refs_dir.mkdir(parents=True, exist_ok=True)
        for spec in downloads:
            if "=" not in spec:
                raise ValueError(f"Invalid --download format (expected label=url_or_file): {spec}")
            raw_label, raw_target = spec.split("=", 1)
            safe_label = re.sub(r"[^A-Za-z0-9_-]+", "_", raw_label.strip()).strip("_") or "ref"
            dl_url = _resolve_download_url(raw_target)
            req = urllib.request.Request(dl_url, headers={"User-Agent": WIKIMEDIA_USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                ct = resp.headers.get("Content-Type", "")
                raw_bytes = resp.read()
            ext = _guess_image_ext(dl_url, ct)
            dest = refs_dir / f"{safe_label}{ext}"
            dest.write_bytes(raw_bytes)
            dims = read_image_dimensions(dest)
            if not dims:
                dest.unlink(missing_ok=True)
                raise ValueError(f"Downloaded file is not a valid PNG/JPEG/WebP image: {dl_url}")
            output["downloaded"].append(
                {
                    "label": raw_label.strip(),
                    "saved_path": str(dest),
                    "width": dims[0],
                    "height": dims[1],
                    "source_url": dl_url,
                }
            )

    print(json.dumps(output, ensure_ascii=False, indent=2))


def _load_or_init_weekly_banners() -> dict[str, Any]:
    existing = load_weekly_banners(WEEKLY_BANNERS_PATH)
    if existing:
        existing.setdefault("schema_version", 1)
        existing.setdefault(
            "default_banner",
            {
                "rel_path": "assets/hero_cast_banner.jpg",
                "spot_name": "",
                "season_label": "スタジオ集合イラスト",
                "alt": DEFAULT_HERO_ALT,
                "caption": "",
            },
        )
        existing.setdefault("cast_reference_sheet", "docs/assets/hero_cast_banner.jpg")
        if not isinstance(existing.get("entries"), list):
            existing["entries"] = []
        return existing
    return {
        "schema_version": 1,
        "default_banner": {
            "rel_path": "assets/hero_cast_banner.jpg",
            "spot_name": "",
            "season_label": "スタジオ集合イラスト",
            "alt": DEFAULT_HERO_ALT,
            "caption": "",
        },
        "cast_reference_sheet": "docs/assets/hero_cast_banner.jpg",
        "entries": [],
    }


def _backup_existing_weekly_banners(week_start: str, new_bytes: bytes, dest_path: Path) -> None:
    """Back up any pre-existing docs/assets/weekly/<week_start>.* before replacing."""
    if not DOCS_WEEKLY_DIR.is_dir():
        return
    stamp = datetime.now(JST).strftime("%Y%m%dT%H%M%S")
    backup_dir = WEEKLY_BANNER_CACHE_DIR / week_start / "replaced"
    for ext in IMAGE_EXTS:
        cand = DOCS_WEEKLY_DIR / f"{week_start}{ext}"
        if not cand.is_file():
            continue
        same_target = cand.resolve() == dest_path.resolve()
        if same_target and cand.read_bytes() == new_bytes:
            continue
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cand, backup_dir / f"{stamp}_{cand.name}")
        if not same_target:
            cand.unlink()


def _resolve_existing_path(raw_path: Any) -> Path | None:
    s = str(raw_path or "").strip()
    if not s:
        return None
    p = Path(s)
    if p.is_file():
        return p
    if not p.is_absolute():
        rel_p = ROOT_DIR / s
        if rel_p.is_file():
            return rel_p
    return None


def _register_weekly_banner(
    week_start: str | None = None,
    meta_json_path: Path | None = None,
    pattern: str | None = None,
    selection_mode: str | None = None,
    image_path: Path | None = None,
    spot_name: str | None = None,
    season_label: str | None = None,
    alt_text: str | None = None,
    caption: str | None = None,
    run_build: bool = True,
    push: bool = False,
) -> dict[str, Any]:
    """Archive all weekend candidate images, validate the selected banner, publish to docs/assets/weekly/, and update registries."""
    banners_data = _load_or_init_weekly_banners()
    entries_by_ws: dict[str, dict[str, Any]] = {
        str(e.get("week_start")): dict(e)
        for e in (banners_data.get("entries") or [])
        if isinstance(e, dict) and e.get("week_start")
    }

    meta_obj: dict[str, Any] = {}
    if meta_json_path is not None:
        if not meta_json_path.is_file():
            raise FileNotFoundError(f"Banner meta JSON not found: {meta_json_path}")
        meta_obj = _load_json(meta_json_path)

    ws = str(week_start or meta_obj.get("week_start") or "").strip()
    if not ws:
        raise ValueError("week_start is required (pass --week-start or provide week_start in --meta-json).")
    start_dt = datetime.strptime(ws, "%Y-%m-%d").date()
    we = str(meta_obj.get("week_end") or (entries_by_ws.get(ws) or {}).get("week_end") or (start_dt + timedelta(days=6)).isoformat()).strip()

    cache_week_dir = WEEKLY_BANNER_CACHE_DIR / ws
    if not meta_obj and not image_path:
        fallback_meta = cache_week_dir / "banner_meta.json"
        if ws not in entries_by_ws and fallback_meta.is_file():
            meta_obj = _load_json(fallback_meta)

    existing_entry = entries_by_ws.get(ws) or {}
    raw_candidates = (
        meta_obj.get("candidates")
        if meta_obj.get("candidates") is not None
        else existing_entry.get("candidates")
    )
    normalized_candidates: list[dict[str, Any]] = []
    chosen_letter = str(
        pattern
        or meta_obj.get("selected_pattern")
        or existing_entry.get("selected_pattern")
        or ""
    ).strip().upper()
    chosen_cand: dict[str, Any] | None = None
    chosen_src: Path | None = None

    if isinstance(raw_candidates, list) and raw_candidates:
        cache_week_dir.mkdir(parents=True, exist_ok=True)
        for idx, raw_c in enumerate(raw_candidates):
            if not isinstance(raw_c, dict):
                continue
            cand = dict(raw_c)
            letter = str(cand.get("pattern") or ["A", "B", "C"][min(idx, 2)]).strip().upper()
            cand["pattern"] = letter
            src = (
                _resolve_existing_path(cand.get("cached_path"))
                or _resolve_existing_path(cand.get("source_path"))
            )
            if not src:
                for ext in IMAGE_EXTS:
                    probe = cache_week_dir / f"pattern_{letter}{ext}"
                    if probe.is_file():
                        src = probe
                        break
            if src is not None:
                c_ext = ".jpg" if src.suffix.lower() == ".jpeg" else src.suffix.lower()
                if c_ext not in IMAGE_EXTS:
                    c_ext = ".jpg"
                cached_dest = cache_week_dir / f"pattern_{letter}{c_ext}"
                if src.resolve() != cached_dest.resolve():
                    shutil.copy2(src, cached_dest)
                cand["cached_path"] = str(cached_dest.relative_to(ROOT_DIR)).replace("\\", "/")
                src = cached_dest
            normalized_candidates.append(cand)

        if not chosen_letter:
            scored = sorted(
                normalized_candidates,
                key=lambda c: float(c.get("qc_score") or 0.0),
                reverse=True,
            )
            if scored:
                chosen_letter = str(scored[0].get("pattern") or "")

        for cand in normalized_candidates:
            if str(cand.get("pattern") or "").upper() == chosen_letter:
                chosen_cand = cand
                chosen_src = (
                    _resolve_existing_path(cand.get("cached_path"))
                    or _resolve_existing_path(cand.get("source_path"))
                )
                break
        if chosen_cand is None and normalized_candidates and not pattern:
            chosen_cand = normalized_candidates[0]
            chosen_letter = str(chosen_cand.get("pattern") or "")
            chosen_src = (
                _resolve_existing_path(chosen_cand.get("cached_path"))
                or _resolve_existing_path(chosen_cand.get("source_path"))
            )
        if pattern and (chosen_cand is None or chosen_src is None):
            raise FileNotFoundError(
                f"Pattern '{chosen_letter}' not found with an archived image for week {ws}."
            )

    if image_path is not None:
        if not image_path.is_file():
            raise FileNotFoundError(f"Banner image file not found: {image_path}")
        chosen_src = image_path
    elif chosen_src is None:
        raise FileNotFoundError(
            f"No banner image resolved for week {ws} (pass --meta-json, --image, or existing archived --pattern)."
        )

    dims = read_image_dimensions(chosen_src)
    if not dims:
        raise ValueError(f"Invalid PNG/JPEG/WebP image file: {chosen_src}")
    if dims[0] < 640 or dims[0] <= dims[1]:
        raise ValueError(
            f"Banner image must be landscape and at least 640px wide (got {dims[0]}x{dims[1]}): {chosen_src}"
        )

    ext = ".jpg" if chosen_src.suffix.lower() == ".jpeg" else chosen_src.suffix.lower()
    if ext not in IMAGE_EXTS:
        raise ValueError(f"Unsupported banner image extension: {chosen_src.suffix}")

    DOCS_WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    dest_rel = f"assets/weekly/{ws}{ext}"
    dest_path = DOCS_WEEKLY_DIR / f"{ws}{ext}"
    if dest_path.resolve() == CAST_REF_SHEET_PATH.resolve():
        raise ValueError("Refusing to overwrite immutable studio cast reference sheet.")

    src_bytes = chosen_src.read_bytes()
    _backup_existing_weekly_banners(ws, src_bytes, dest_path)
    if chosen_src.resolve() != dest_path.resolve():
        shutil.copy2(chosen_src, dest_path)

    resolved_spot = str(
        spot_name
        if spot_name is not None
        else (chosen_cand or {}).get("spot_name")
        or existing_entry.get("spot_name")
        or ""
    ).strip()
    resolved_season = str(
        season_label
        if season_label is not None
        else (chosen_cand or {}).get("season_label")
        or existing_entry.get("season_label")
        or ""
    ).strip()
    resolved_caption = str(
        caption
        if caption is not None
        else (chosen_cand or {}).get("caption")
        or existing_entry.get("caption")
        or resolved_spot
    ).strip()
    resolved_alt = str(
        alt_text
        if alt_text is not None
        else (chosen_cand or {}).get("alt")
        or existing_entry.get("alt")
        or (f"{resolved_spot}（小春・平蔵と専門家ゲスト）" if resolved_spot else DEFAULT_HERO_ALT)
    ).strip()
    resolved_mode = str(
        selection_mode
        or ("user" if pattern and not meta_json_path else None)
        or meta_obj.get("selection_mode")
        or existing_entry.get("selection_mode")
        or "auto"
    ).strip()

    entry_out: dict[str, Any] = {
        "week_start": ws,
        "week_end": we,
        "rel_path": dest_rel,
        "width": dims[0],
        "height": dims[1],
        "spot_name": resolved_spot,
        "season_label": resolved_season,
        "caption": resolved_caption,
        "alt": resolved_alt,
        "selected_pattern": chosen_letter,
        "selection_mode": resolved_mode,
        "candidates": normalized_candidates,
        "updated_at": datetime.now(JST).isoformat(timespec="seconds"),
    }
    entries_by_ws[ws] = entry_out
    banners_data["entries"] = [entries_by_ws[k] for k in sorted(entries_by_ws)]
    WEEKLY_BANNERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    WEEKLY_BANNERS_PATH.write_text(
        json.dumps(banners_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Saved {WEEKLY_BANNERS_PATH} (week={ws}, pattern={chosen_letter or '-'}, rel_path={dest_rel})")

    if EDITORIAL_PLAN_PATH.is_file():
        ed_plan = _load_json(EDITORIAL_PLAN_PATH)
        changed = False
        for wk in ed_plan.get("weeks") or []:
            if isinstance(wk, dict) and str(wk.get("week_start") or "") == ws:
                if wk.get("banner_image") != dest_rel:
                    wk["banner_image"] = dest_rel
                    changed = True
        if changed:
            EDITORIAL_PLAN_PATH.write_text(
                json.dumps(ed_plan, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"Updated banner_image in {EDITORIAL_PLAN_PATH} for {ws} -> {dest_rel}")

    if run_build:
        _run_python_script("build_site.py", [])

    if push:
        add_paths = [
            p
            for p in ("data/weekly_banners.json", "data/editorial_plan.json", "docs/")
            if (ROOT_DIR / p).exists()
        ]
        _run_git(["add", *add_paths])
        status = _run_git(["status", "--porcelain"])
        if status.stdout.strip():
            _run_git(["commit", "-m", f"banner: update weekly banner {ws}"])
            _run_git(["pull", "--rebase"])
            _run_git(["push"])
            print(f"Pushed weekly banner {ws} to origin/main.")
        else:
            print("No banner or site changes to commit.")

    return entry_out


def cmd_set_weekly_banner(args: argparse.Namespace) -> None:
    meta_path = Path(args.meta_json) if args.meta_json else None
    img_path = Path(args.image) if args.image else None
    entry = _register_weekly_banner(
        week_start=args.week_start,
        meta_json_path=meta_path,
        pattern=args.pattern,
        selection_mode=args.selection_mode,
        image_path=img_path,
        spot_name=args.spot_name,
        season_label=args.season_label,
        alt_text=args.alt,
        caption=args.caption,
        run_build=not args.no_build,
        push=args.push,
    )
    print(f"STATUS: BANNER_UPDATED ({entry['week_start']} -> {entry['rel_path']})")


def _find_week_plan_details(
    existing_plan: dict[str, Any] | None,
    start_dt: date,
    end_dt: date,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    start_str = start_dt.isoformat()
    end_str = end_dt.isoformat()
    week_arc: dict[str, Any] = {}
    if isinstance(existing_plan, dict):
        for wk in existing_plan.get("weeks") or []:
            if isinstance(wk, dict) and str(wk.get("week_start") or "") == start_str:
                week_arc = dict(wk.get("weekly_arc") or {})
                break
        if not week_arc and str(existing_plan.get("week_start") or "") == start_str:
            week_arc = dict(existing_plan.get("weekly_arc") or {})
        guides = [
            g
            for g in (existing_plan.get("daily_guides") or [])
            if isinstance(g, dict) and start_str <= str(g.get("date") or "") <= end_str
        ]
    else:
        guides = []
    return week_arc, guides


def cmd_prepare_weekly(args: argparse.Namespace) -> None:
    if not args.no_pull:
        _run_git(["pull", "--rebase"])

    now_jst = datetime.now(JST)
    existing_plan = _load_optional_json(EDITORIAL_PLAN_PATH, None)
    start_str = args.start_date or _default_next_monday(now_jst, existing_plan=existing_plan).isoformat()
    start_dt = datetime.strptime(start_str, "%Y-%m-%d").date()
    end_dt = start_dt + timedelta(days=6)

    existing_weeks: set[str] = set()
    if existing_plan:
        existing_weeks = {
            str(w.get("week_start"))
            for w in (existing_plan.get("weeks") or [])
            if isinstance(w, dict) and w.get("week_start")
        }
        if not existing_weeks and existing_plan.get("week_start"):
            existing_weeks.add(str(existing_plan["week_start"]))

    plan_exists = start_str in existing_weeks
    banner_exists = _has_weekly_banner(start_str)

    if plan_exists and banner_exists:
        print(f"STATUS: ALREADY_PLANNED ({start_str}..{end_dt.isoformat()})")
        return

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    past_spots = _recent_banner_spots_summary()
    banner_guide_path = CACHE_DIR / f"local_weekly_banner_guide_{start_str}.md"

    if plan_exists and not banner_exists:
        week_arc, daily_guides = _find_week_plan_details(existing_plan, start_dt, end_dt)
        season_ctx = _describe_season_context(start_dt, end_dt)
        banner_briefing_path = CACHE_DIR / f"local_weekly_banner_briefing_{start_str}.json"
        banner_briefing_payload = {
            "week_start": start_str,
            "week_end": end_dt.isoformat(),
            "weekly_arc": week_arc,
            "season_context": season_ctx,
            "daily_guides": daily_guides,
            "cast_reference_sheet": str(CAST_REF_SHEET_PATH),
            "meta_target": str(WEEKLY_BANNER_CACHE_DIR / start_str / "banner_meta.json"),
            "proposals_target": str(WEEKLY_BANNER_CACHE_DIR / start_str / "proposals.md"),
        }
        banner_briefing_path.write_text(
            json.dumps(banner_briefing_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        banner_guide_path.write_text(
            _build_weekly_banner_guide_md(start_dt, end_dt, week_arc, daily_guides, past_spots),
            encoding="utf-8",
        )
        print(f"STATUS: READY_FOR_BANNER_ONLY ({start_str}..{end_dt.isoformat()})")
        print(f"BANNER_BRIEFING_JSON: {banner_briefing_path}")
        print(f"BANNER_GUIDE_MD: {banner_guide_path}")
        return

    themes = _load_json(CONFIG_DIR / "weekly_themes.json")
    special_days = _load_optional_json(CONFIG_DIR / "special_days.json", {"recurring": [], "dated_events": []})
    program_schedule = _load_optional_json(CONFIG_DIR / "program_schedule.json", None)
    topic_history_data = _load_optional_json(DATA_DIR / "topic_history.json", {"entries": []})
    topic_entries = topic_history_data.get("entries", [])
    spots_cfg = load_kodaira_spots()
    usage_map = compute_spot_usage(
        spots_cfg,
        topic_entries,
        editorial_plan=existing_plan,
        reference_date=start_dt,
        exclude_date_range=(start_str, end_dt.isoformat()),
    )
    recommended_fresh_spots = select_balanced_spot_candidates(
        spots_cfg,
        usage_map,
        start_dt,
        count=20,
    )
    spot_cooldown_text = format_spot_cooldown_block(spots_cfg, usage_map, start_dt)
    spot_candidates_text = format_spot_candidates_block(spots_cfg, recommended_fresh_spots)

    skeleton = _build_week_skeleton(
        start_dt,
        7,
        themes,
        special_days,
        topic_entries,
        program_schedule=program_schedule,
    )
    recent_history = _format_recent_history(start_dt, topic_entries, existing_plan=existing_plan)

    briefing_path = CACHE_DIR / f"local_weekly_briefing_{start_str}.json"
    draft_path = CACHE_DIR / f"local_weekly_draft_{start_str}.json"
    briefing_payload = {
        "week_start": start_str,
        "week_end": end_dt.isoformat(),
        "lookahead_end": (start_dt + timedelta(days=13)).isoformat(),
        "skeleton": skeleton,
        "recent_history_text": recent_history,
        "spot_cooldown_text": spot_cooldown_text,
        "spot_candidates_text": spot_candidates_text,
        "recommended_fresh_spots": [
            {
                "id": s["id"],
                "name": s["name"],
                "category": s["category"],
                "category_label": s.get("category_label", ""),
                "area": s.get("area", ""),
                "station": s.get("station", ""),
                "summary": s.get("summary", ""),
                "best_seasons": s.get("best_seasons", []),
                "disaster_angles": s.get("disaster_angles", []),
                "user_request_priority": bool(s.get("user_request_priority")),
            }
            for s in recommended_fresh_spots
        ],
        "spot_dedup_policy": {
            "cooldown_days": SPOT_COOLDOWN_DAYS,
            "allow_exception_for_major_renewal_or_timely_event": True,
            "preserve_freshness": True,
            "note": "原則90日クールダウンを守り16ジャンルから多様に選ぶ。大規模リニューアル・新装開店・開催当日の大型イベントは例外可。鮮度を優先し最新ローカルニュースが出たら柔軟に差し替え可。",
        },
        "season_context": _describe_season_context(start_dt, end_dt),
        "rules": {
            "must_cover_all_7_dates": [r["date"] for r in skeleton],
            "respect_preplanned_expert_topics": True,
            "respect_schedule_locked_and_special_request": True,
            "avoid_90d_cooldown_spots_unless_major_event": True,
            "diverse_areas_and_categories_across_week": True,
            "editorial_special_must_be_null_when_has_existing_special": True,
            "editorial_special_cap_per_week": "1 to 2 days",
            "verify_current_year_dates_only": start_dt.year,
        },
        "output_schema": {
            "weekly_arc": {"title": "今週の番組キャッチタイトル", "concept": "今週の編集方針（1〜2文）"},
            "daily_guides": [
                {
                    "date": "YYYY-MM-DD",
                    "focus_area": "小平市内の重点エリア",
                    "kodaira_angle": "ワクワクする小平まち・暮らしネタ切り口",
                    "search_hints": ["検索キーワード1", "キーワード2"],
                    "expert_angle": "専門家テーマと小平を絡める切り口",
                    "editorial_special": {
                        "title": "特集タイトル",
                        "phase_label": "編集長ワクワク特集",
                        "extra_minutes": 3,
                        "theme_focus": "具体的企画内容",
                    },
                }
            ],
            "upcoming_ideas": ["企画アイデア1", "アイデア2", "アイデア3"],
        },
    }
    briefing_path.write_text(json.dumps(briefing_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    banner_guide_path.write_text(
        _build_weekly_banner_guide_md(start_dt, end_dt, {}, skeleton, past_spots),
        encoding="utf-8",
    )

    print(f"STATUS: READY_FOR_WEEKLY_PLAN ({start_str}..{end_dt.isoformat()})")
    print(f"BRIEFING_JSON: {briefing_path}")
    print(f"DRAFT_TARGET: {draft_path}")
    print(f"BANNER_GUIDE_MD: {banner_guide_path}")


def cmd_finalize_weekly(args: argparse.Namespace) -> None:
    now_jst = datetime.now(JST)
    existing_plan = _load_optional_json(EDITORIAL_PLAN_PATH, None)
    start_str = args.start_date or _default_next_monday(now_jst, existing_plan=existing_plan).isoformat()
    datetime.strptime(start_str, "%Y-%m-%d")

    draft_path = Path(args.draft) if args.draft else (CACHE_DIR / f"local_weekly_draft_{start_str}.json")
    briefing_path = CACHE_DIR / f"local_weekly_briefing_{start_str}.json"
    if not draft_path.exists():
        raise FileNotFoundError(f"Weekly draft JSON not found: {draft_path}")
    if not briefing_path.exists():
        raise FileNotFoundError(f"Weekly briefing JSON not found: {briefing_path}")

    raw_plan = _load_json(draft_path)
    briefing = _load_json(briefing_path)
    skeleton = briefing["skeleton"]

    arc = raw_plan.get("weekly_arc") or {}
    if not str(arc.get("title") or "").strip():
        raise ValueError("Weekly draft missing non-empty weekly_arc.title")
    raw_dates = {
        str(g.get("date"))
        for g in (raw_plan.get("daily_guides") or [])
        if isinstance(g, dict) and g.get("date")
    }
    expected_dates = {r["date"] for r in skeleton}
    missing = sorted(expected_dates - raw_dates)
    if missing:
        raise ValueError(f"Weekly draft daily_guides missing dates: {missing}")
    ideas = [str(x).strip() for x in (raw_plan.get("upcoming_ideas") or []) if str(x).strip()]
    if not ideas:
        raise ValueError("Weekly draft missing non-empty upcoming_ideas")

    spots_cfg = load_kodaira_spots()
    new_week_plan = _normalize_editorial_plan(
        raw_plan,
        skeleton,
        research_model="antigravity-local",
        planner_model="antigravity-local",
        spots_cfg=spots_cfg,
    )
    merged_plan = merge_editorial_plans(existing_plan, new_week_plan, now_jst)

    EDITORIAL_PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    EDITORIAL_PLAN_PATH.write_text(json.dumps(merged_plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {EDITORIAL_PLAN_PATH} (week_start={start_str})")

    topic_entries = _load_optional_json(DATA_DIR / "topic_history.json", {"entries": []}).get("entries", [])
    overlaps = audit_plan_spot_overlaps(spots_cfg, topic_entries, merged_plan)
    for ov in overlaps:
        print(
            f"WARNING: SPOT_OVERLAP {ov['spot_name']} ({ov['spot_id']}): "
            f"{ov['date_a']} [{ov['source_a']}] -> {ov['date_b']} [{ov['source_b']}] "
            f"(gap={ov['gap_days']}d < cooldown={ov['cooldown_days']}d)"
        )

    default_banner_meta = WEEKLY_BANNER_CACHE_DIR / start_str / "banner_meta.json"
    banner_meta_path = (
        Path(args.banner_meta)
        if args.banner_meta
        else (default_banner_meta if default_banner_meta.is_file() else None)
    )
    if banner_meta_path is not None:
        _register_weekly_banner(
            week_start=start_str,
            meta_json_path=banner_meta_path,
            pattern=args.banner_pattern,
            run_build=False,
            push=False,
        )

    _run_python_script("build_site.py", [])

    if args.push:
        add_paths = [
            p
            for p in ("data/editorial_plan.json", "data/weekly_banners.json", "docs/")
            if (ROOT_DIR / p).exists()
        ]
        _run_git(["add", *add_paths])
        status = _run_git(["status", "--porcelain"])
        if status.stdout.strip():
            _run_git(["commit", "-m", "editorial: update weekly program plan"])
            _run_git(["pull", "--rebase"])
            _run_git(["push"])
            print("Pushed weekly editorial plan and site to origin/main.")
        else:
            print("No editorial_plan.json or docs changes to commit.")

    print(f"STATUS: WEEKLY_COMPLETE ({start_str})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Local Antigravity automation helper for kb-radio")
    sub = parser.add_subparsers(dest="command", required=True)

    p_pd = sub.add_parser("prepare-daily", help="Prepare daily briefing and prompt for local authoring")
    p_pd.add_argument("--date", default=None, help="Target date YYYY-MM-DD (default: today JST)")
    p_pd.add_argument("--no-pull", action="store_true", help="Skip git pull --rebase")

    p_fd = sub.add_parser("finalize-daily", help="Validate draft, run Gemini TTS, rebuild site, and optionally push")
    p_fd.add_argument("--date", default=None, help="Target date YYYY-MM-DD (default: today JST)")
    p_fd.add_argument("--draft", default=None, help="Path to raw draft JSON")
    p_fd.add_argument("--tts-only", action="store_true", help="Skip draft assembly and run TTS/site/push for existing episode.json")
    p_fd.add_argument("--no-tts", action="store_true", help="Skip TTS audio synthesis")
    p_fd.add_argument("--push", action="store_true", help="Commit and push generated assets to origin/main")
    p_fd.add_argument("--allow-char-overflow", action="store_true", help="Allow display_chars outside hard bounds")

    p_pw = sub.add_parser("prepare-weekly", help="Prepare weekly editorial skeleton, briefing, and banner guide")
    p_pw.add_argument("--start-date", default=None, help="Week start Monday YYYY-MM-DD")
    p_pw.add_argument("--no-pull", action="store_true", help="Skip git pull --rebase")

    p_fbr = sub.add_parser("fetch-banner-refs", help="Search Wikimedia Commons and download real Kodaira reference photos")
    p_fbr.add_argument("--week-start", required=True, help="Target week start Monday YYYY-MM-DD")
    p_fbr.add_argument("--commons-search", action="append", default=[], help="Wikimedia Commons search query")
    p_fbr.add_argument("--download", action="append", default=[], help="Download reference as label=URL or label=File:Title")

    p_swb = sub.add_parser("set-weekly-banner", help="Archive 3 banner candidates, publish selected banner, rebuild site, and optionally push")
    p_swb.add_argument("--week-start", default=None, help="Target week start Monday YYYY-MM-DD")
    p_swb.add_argument("--meta-json", default=None, help="Path to banner_meta.json with 3 candidates")
    p_swb.add_argument("--pattern", default=None, help="Selected or switched pattern letter (A|B|C)")
    p_swb.add_argument("--selection-mode", default=None, help="Selection mode (auto|user)")
    p_swb.add_argument("--image", default=None, help="Manual single image path override")
    p_swb.add_argument("--spot-name", default=None, help="Override spot name")
    p_swb.add_argument("--season-label", default=None, help="Override season label")
    p_swb.add_argument("--caption", default=None, help="Override display caption")
    p_swb.add_argument("--alt", default=None, help="Override image alt text")
    p_swb.add_argument("--no-build", action="store_true", help="Skip build_site.py")
    p_swb.add_argument("--push", action="store_true", help="Commit and push updated weekly_banners.json and docs")

    p_fw = sub.add_parser("finalize-weekly", help="Merge weekly plan, optionally register weekly banner, rebuild site, and push")
    p_fw.add_argument("--start-date", default=None, help="Week start Monday YYYY-MM-DD")
    p_fw.add_argument("--draft", default=None, help="Path to weekly draft JSON")
    p_fw.add_argument("--banner-meta", default=None, help="Optional path to banner_meta.json")
    p_fw.add_argument("--banner-pattern", default=None, help="Optional pattern override (A|B|C)")
    p_fw.add_argument("--push", action="store_true", help="Commit and push updated editorial_plan.json, weekly_banners.json, and docs")

    args = parser.parse_args()
    handlers = {
        "prepare-daily": cmd_prepare_daily,
        "finalize-daily": cmd_finalize_daily,
        "prepare-weekly": cmd_prepare_weekly,
        "fetch-banner-refs": cmd_fetch_banner_refs,
        "set-weekly-banner": cmd_set_weekly_banner,
        "finalize-weekly": cmd_finalize_weekly,
    }
    handlers[args.command](args)


if __name__ == "__main__":
    main()
