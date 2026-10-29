"""Map normalized clock values to the four report periods."""
import re


def entity_period(entity: dict) -> str | None:
    if entity.get("subtype") == "时段":
        word = entity.get("normalized") or entity["text"]
        groups = {
            "上午": {"清晨", "早晨", "早上", "上午"}, "中午": {"正午", "中午"},
            "下午": {"下午", "傍晚"}, "晚上": {"晚上", "夜间", "夜里", "深夜", "凌晨"},
        }
        return next((key for key, values in groups.items() if word in values), None)
    if entity.get("subtype") not in {"时刻", "时刻区间"}:
        return None
    value = entity.get("normalized") or entity["text"]
    match = re.match(r"(\d{1,2}):", value)
    if not match:
        return None
    hour = int(match.group(1))
    return "上午" if 5 <= hour < 12 else "中午" if 12 <= hour < 14 else "下午" if 14 <= hour < 19 else "晚上"
