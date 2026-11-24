"""Live weather (Open-Meteo), earthquake (P2PQuake v2), and verified official links for Kodaira City."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import requests

JST = timezone(timedelta(hours=9))
KODAIRA_LAT = 35.7285
KODAIRA_LON = 139.4775
USER_AGENT = "KodairaBousaiRadio/2.0 (+https://github.com/kb-radio)"

WMO_WEATHER_JA = {
    0: "快晴",
    1: "おおむね晴れ",
    2: "晴れ時々曇り",
    3: "曇り",
    45: "霧",
    48: "着氷性の霧",
    51: "弱い霧雨",
    53: "霧雨",
    55: "やや強い霧雨",
    56: "弱い着氷性の霧雨",
    57: "着氷性の霧雨",
    61: "小雨",
    63: "雨",
    65: "強い雨",
    66: "弱い着氷性の雨",
    67: "着氷性の雨",
    71: "小雪",
    73: "雪",
    75: "大雪",
    77: "霧雪",
    80: "弱いにわか雨",
    81: "にわか雨",
    82: "激しいにわか雨",
    85: "弱いにわか雪",
    86: "にわか雪",
    95: "雷雨",
    96: "ひょうを伴う雷雨",
    99: "激しいひょうを伴う雷雨",
}

SCALE_MAP = {
    10: "震度1",
    20: "震度2",
    30: "震度3",
    40: "震度4",
    45: "震度5弱",
    50: "震度5強",
    55: "震度6弱",
    60: "震度6強",
    70: "震度7",
}

KANTO_KEYWORDS = (
    "東京",
    "千葉",
    "埼玉",
    "神奈川",
    "茨城",
    "栃木",
    "群馬",
    "房総",
    "相模",
    "伊豆",
    "小笠原",
    "多摩",
)


def _weather_code_to_ja(code: Any) -> str:
    try:
        c = int(code)
    except (TypeError, ValueError):
        return "晴れまたは曇り"
    return WMO_WEATHER_JA.get(c, "曇りや雨など変わりやすい天気")


def fetch_kodaira_weather(timeout: float = 10.0) -> dict[str, Any]:
    """Fetch 3-day weather and current conditions for Kodaira City via Open-Meteo."""
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": KODAIRA_LAT,
        "longitude": KODAIRA_LON,
        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "Asia/Tokyo",
        "forecast_days": 3,
    }
    try:
        resp = requests.get(
            url, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout
        )
        resp.raise_for_status()
        raw = resp.json()

        cur = raw.get("current", {})
        daily = raw.get("daily", {})
        days: list[dict[str, Any]] = []
        times = daily.get("time", [])
        codes = daily.get("weather_code", [])
        t_max = daily.get("temperature_2m_max", [])
        t_min = daily.get("temperature_2m_min", [])
        precip = daily.get("precipitation_probability_max", [])

        for i, d_str in enumerate(times):
            days.append(
                {
                    "date": d_str,
                    "weather": _weather_code_to_ja(codes[i] if i < len(codes) else None),
                    "temp_max_c": t_max[i] if i < len(t_max) else None,
                    "temp_min_c": t_min[i] if i < len(t_min) else None,
                    "precip_prob_max": precip[i] if i < len(precip) else None,
                }
            )

        humidity = cur.get("relative_humidity_2m")
        today_max = days[0]["temp_max_c"] if days else None
        today_min = days[0]["temp_min_c"] if days else None
        advisories: list[str] = []
        if today_max is not None and today_min is not None and (today_max - today_min) >= 9.0:
            advisories.append("朝晩と日中の寒暖差が大きいので服装調整に注意")
        if humidity is not None and humidity <= 45:
            advisories.append("空気が乾燥しているため火の元・のどの保湿に注意")
        if days and (days[0].get("precip_prob_max") or 0) >= 50:
            advisories.append("降水確率が高めのため雨具や路面の安全に注意")
        if not advisories:
            advisories.append("季節の変わり目に備えて体調管理と身の回りの安全確認を")

        return {
            "ok": True,
            "source": "Open-Meteo (小平市座標)",
            "fetched_at_jst": datetime.now(JST).isoformat(timespec="seconds"),
            "current": {
                "temperature_c": cur.get("temperature_2m"),
                "humidity_pct": humidity,
                "weather": _weather_code_to_ja(cur.get("weather_code")),
                "wind_speed_kmh": cur.get("wind_speed_10m"),
            },
            "daily": days,
            "advisories": advisories,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "source": "Open-Meteo fallback",
            "error": str(exc),
            "fetched_at_jst": datetime.now(JST).isoformat(timespec="seconds"),
            "current": {
                "temperature_c": None,
                "humidity_pct": None,
                "weather": "季節らしい空模様",
                "wind_speed_kmh": None,
            },
            "daily": [],
            "advisories": ["最新のお天気は気象庁ホームページ等もあわせてご確認ください"],
        }


def fetch_recent_earthquakes(limit: int = 10, hours: int = 48, timeout: float = 10.0) -> list[dict[str, Any]]:
    """Fetch recent earthquakes from P2PQuake JSON API v2 (code 551)."""
    url = "https://api.p2pquake.net/v2/history"
    params = {"codes": 551, "limit": limit}
    try:
        resp = requests.get(
            url, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout
        )
        resp.raise_for_status()
        items = resp.json()
        if not isinstance(items, list):
            return []

        now_jst = datetime.now(JST)
        cutoff = now_jst - timedelta(hours=hours)
        parsed: list[dict[str, Any]] = []

        for item in items:
            eq = item.get("earthquake") or {}
            hypo = eq.get("hypocenter") or {}
            time_str = eq.get("time") or item.get("time") or ""
            hypo_name = hypo.get("name") or "調査中"
            max_scale_num = eq.get("maxScale")
            max_scale_ja = SCALE_MAP.get(max_scale_num, "震度情報なし")
            magnitude = hypo.get("magnitude")
            tsunami = eq.get("domesticTsunami") or ""

            # Parse timestamp "YYYY/MM/DD HH:MM:SS" or ISO
            dt_jst: datetime | None = None
            for fmt in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
                try:
                    dt_jst = datetime.strptime(time_str[:19], fmt).replace(tzinfo=JST)
                    break
                except ValueError:
                    continue

            points = item.get("points") or []
            tokyo_points = [
                f"{p.get('addr', '')}({SCALE_MAP.get(p.get('scale'), '')})"
                for p in points
                if "東京" in (p.get("pref") or "")
            ]
            is_kanto = bool(tokyo_points) or any(k in hypo_name for k in KANTO_KEYWORDS)

            if dt_jst is not None and dt_jst < cutoff:
                continue

            parsed.append(
                {
                    "time": time_str,
                    "hypocenter": hypo_name,
                    "magnitude": magnitude,
                    "max_scale": max_scale_ja,
                    "max_scale_num": max_scale_num or -1,
                    "tsunami": tsunami,
                    "is_kanto_or_tokyo": is_kanto,
                    "tokyo_points": tokyo_points[:5],
                }
            )

        # Sort prioritizing Kanto/Tokyo and higher intensity, then newest
        parsed.sort(
            key=lambda q: (
                1 if q["is_kanto_or_tokyo"] else 0,
                q["max_scale_num"],
                q["time"],
            ),
            reverse=True,
        )
        return parsed
    except Exception:  # noqa: BLE001
        return []


def get_verified_kodaira_links() -> list[dict[str, str]]:
    """Return curated verified official links relevant to Kodaira disaster preparedness."""
    return [
        {
            "category": "小平市公式",
            "title": "東京都小平市 公式ホームページ",
            "url": "https://www.city.kodaira.tokyo.jp/",
            "note": "市政ニュース・イベント・防災緊急情報の一次発信元",
        },
        {
            "category": "防災マップ",
            "title": "小平市防災マップ（避難所・給水拠点・備え）",
            "url": "https://www.city.kodaira.tokyo.jp/kurashi/036/036337.html",
            "note": "避難場所や防災施設、安否確認方法がまとまった小平市公式ページ",
        },
        {
            "category": "ハザードマップ",
            "title": "小平市ハザードマップ（浸水予想・土砂災害警戒）",
            "url": "https://www.city.kodaira.tokyo.jp/kurashi/012/012389.html",
            "note": "大雨や台風時の浸水リスクやマイ・タイムライン作成に活用",
        },
        {
            "category": "防災補助制度",
            "title": "小平市 感震ブレーカー購入費補助金について",
            "url": "https://www.city.kodaira.tokyo.jp/kurashi/116/116518.html",
            "note": "地震に伴う通電火災対策の補助制度（申請条件・予算状況を事前確認）",
        },
        {
            "category": "備蓄チェック",
            "title": "東京備蓄ナビ（東京都）",
            "url": "https://www.bichiku.metro.tokyo.lg.jp/",
            "note": "家族構成や住まいに合わせた必要備蓄品・数量をシミュレーション",
        },
        {
            "category": "東京都防災",
            "title": "東京都防災ホームページ",
            "url": "https://www.bousai.metro.tokyo.lg.jp/",
            "note": "東京都防災アプリ・在宅避難キャンペーン・都内防災情報",
        },
        {
            "category": "気象・地震",
            "title": "気象庁ホームページ",
            "url": "https://www.jma.go.jp/jma/index.html",
            "note": "警報・注意報、キキクル（危険度分布）、地震・津波の公式発表",
        },
    ]


def collect_live_briefing() -> dict[str, Any]:
    """Gather weather, recent earthquakes, and verified official links into one bundle."""
    weather = fetch_kodaira_weather()
    earthquakes = fetch_recent_earthquakes()
    links = get_verified_kodaira_links()
    return {
        "weather": weather,
        "earthquakes": earthquakes,
        "verified_links": links,
    }


if __name__ == "__main__":
    import json

    bundle = collect_live_briefing()
    print("=== Kodaira Live Weather ===")
    print(json.dumps(bundle["weather"], ensure_ascii=False, indent=2))
    print("\n=== Recent Earthquakes (48h) ===")
    print(json.dumps(bundle["earthquakes"][:5], ensure_ascii=False, indent=2))
    print(f"\nVerified Links Count: {len(bundle['verified_links'])}")
