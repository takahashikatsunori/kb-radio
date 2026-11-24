"""Local Antigravity automation helper: prepares briefings, validates drafts, runs TTS/site build, and pushes."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

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
from plan_weekly_editorial import (
    EDITORIAL_PLAN_PATH,
    _build_week_skeleton,
    _default_next_monday,
    _format_recent_history,
    _normalize_editorial_plan,
    merge_editorial_plans,
)
from schedule_calendar import resolve_day_plan, resolve_tomorrow_preview

ROOT_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT_DIR / ".cache"
DOCS_AUDIO_DIR = ROOT_DIR / "docs" / "audio"
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

### ② {guest['name']} 過去{EXPERT_HISTORY_DAYS}日間の既出キーワード
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
   - 難読の小平地名（小平市=こだいら市（文頭等で「こだまし」と誤読されやすいため）、小川町=おがわちょう、上水本町=じょうすいほんちょう、津田町=つだまち、御幸町=みゆきちょう、大沼町=おおぬまちょう、鷹の台=たかのだい、狭山・境緑道=さやま・さかいりょくどう 等）や、読み間違いやすい人名・英略語（XRAIN=エックスレイン、GPS=ジーピーエス 等）だけをかな／カタカナに開く。
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
    dedup_ctx = build_dedup_context(target_date, day_plan, topic_history_data.get("entries", []))
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


def cmd_prepare_weekly(args: argparse.Namespace) -> None:
    if not args.no_pull:
        _run_git(["pull", "--rebase"])

    now_jst = datetime.now(JST)
    existing_plan = _load_optional_json(EDITORIAL_PLAN_PATH, None)
    start_str = args.start_date or _default_next_monday(now_jst, existing_plan=existing_plan).isoformat()
    start_dt = datetime.strptime(start_str, "%Y-%m-%d").date()
    end_dt = start_dt + timedelta(days=6)

    if existing_plan:
        existing_weeks = {
            str(w.get("week_start"))
            for w in (existing_plan.get("weeks") or [])
            if isinstance(w, dict) and w.get("week_start")
        }
        if not existing_weeks and existing_plan.get("week_start"):
            existing_weeks.add(str(existing_plan["week_start"]))
        if start_dt.isoformat() in existing_weeks:
            print(f"STATUS: ALREADY_PLANNED ({start_dt.isoformat()}..{end_dt.isoformat()})")
            return

    themes = _load_json(CONFIG_DIR / "weekly_themes.json")
    special_days = _load_optional_json(CONFIG_DIR / "special_days.json", {"recurring": [], "dated_events": []})
    program_schedule = _load_optional_json(CONFIG_DIR / "program_schedule.json", None)
    topic_history_data = _load_optional_json(DATA_DIR / "topic_history.json", {"entries": []})
    topic_entries = topic_history_data.get("entries", [])

    skeleton = _build_week_skeleton(
        start_dt,
        7,
        themes,
        special_days,
        topic_entries,
        program_schedule=program_schedule,
    )
    recent_history = _format_recent_history(start_dt, topic_entries)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    briefing_path = CACHE_DIR / f"local_weekly_briefing_{start_dt.isoformat()}.json"
    draft_path = CACHE_DIR / f"local_weekly_draft_{start_dt.isoformat()}.json"
    briefing_payload = {
        "week_start": start_dt.isoformat(),
        "week_end": end_dt.isoformat(),
        "lookahead_end": (start_dt + timedelta(days=13)).isoformat(),
        "skeleton": skeleton,
        "recent_history_text": recent_history,
        "rules": {
            "must_cover_all_7_dates": [r["date"] for r in skeleton],
            "respect_preplanned_expert_topics": True,
            "respect_schedule_locked_and_special_request": True,
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

    print(f"STATUS: READY_FOR_WEEKLY_PLAN ({start_dt.isoformat()}..{end_dt.isoformat()})")
    print(f"BRIEFING_JSON: {briefing_path}")
    print(f"DRAFT_TARGET: {draft_path}")


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

    new_week_plan = _normalize_editorial_plan(
        raw_plan,
        skeleton,
        research_model="antigravity-local",
        planner_model="antigravity-local",
    )
    merged_plan = merge_editorial_plans(existing_plan, new_week_plan, now_jst)

    EDITORIAL_PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    EDITORIAL_PLAN_PATH.write_text(json.dumps(merged_plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {EDITORIAL_PLAN_PATH} (week_start={start_str})")

    _run_python_script("build_site.py", [])

    if args.push:
        _run_git(["add", "data/editorial_plan.json", "docs/"])
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

    p_pw = sub.add_parser("prepare-weekly", help="Prepare weekly editorial skeleton and briefing")
    p_pw.add_argument("--start-date", default=None, help="Week start Monday YYYY-MM-DD")
    p_pw.add_argument("--no-pull", action="store_true", help="Skip git pull --rebase")

    p_fw = sub.add_parser("finalize-weekly", help="Merge weekly plan, rebuild site, and optionally push")
    p_fw.add_argument("--start-date", default=None, help="Week start Monday YYYY-MM-DD")
    p_fw.add_argument("--draft", default=None, help="Path to weekly draft JSON")
    p_fw.add_argument("--push", action="store_true", help="Commit and push updated editorial_plan.json and docs")

    args = parser.parse_args()
    handlers = {
        "prepare-daily": cmd_prepare_daily,
        "finalize-daily": cmd_finalize_daily,
        "prepare-weekly": cmd_prepare_weekly,
        "finalize-weekly": cmd_finalize_weekly,
    }
    handlers[args.command](args)


if __name__ == "__main__":
    main()
