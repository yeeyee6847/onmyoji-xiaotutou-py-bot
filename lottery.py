"""与 Web 层独立的抽奖逻辑，之后可由 Discord bot 调用。"""
import copy
import secrets
import uuid
from datetime import datetime, timezone


class DrawError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def validate_settings(data):
    if not isinstance(data, dict):
        raise DrawError("提交的设置格式不正确。")
    result = {}
    for key, label in [("title", "抽奖标题"), ("host", "主办人"), ("prize", "奖品名称")]:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 120:
            raise DrawError(f"请填写{label}，最多 120 字。")
        result[key] = value.strip()
    if data.get("mode") not in ("elimination", "instant"):
        raise DrawError("请选择抽奖模式。")
    result["mode"] = data["mode"]
    try:
        scheduled = datetime.fromisoformat(data.get("scheduled_at", "").replace("Z", "+00:00"))
        if scheduled.tzinfo is None:
            raise ValueError
    except (TypeError, ValueError, AttributeError):
        raise DrawError("请设置有效的抽奖时间。")
    result["scheduled_at"] = scheduled.astimezone(timezone.utc).isoformat()
    participants = data.get("participants")
    if not isinstance(participants, list) or not 2 <= len(participants) <= 100:
        raise DrawError("请添加 2–100 位参与者。")
    names, numbers, people = set(), set(), []
    for person in participants:
        if not isinstance(person, dict):
            raise DrawError("参与者格式不正确。")
        name, number = person.get("name"), person.get("number")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
            raise DrawError("参与者名称需要 1–60 字。")
        name = name.strip()
        if type(number) is not int or not 1 <= number <= 100:
            raise DrawError(f"{name} 的号码必须是 1–100 的整数。")
        if name.casefold() in names:
            raise DrawError(f"参与者名称「{name}」重复了。")
        if number in numbers:
            raise DrawError(f"号码 {number} 重复了，每人需选择不同号码。")
        names.add(name.casefold())
        numbers.add(number)
        people.append({"name": name, "number": number})
    result["participants"] = people
    return result


def new_draw(settings, practice=False):
    state = copy.deepcopy(validate_settings(settings))
    cards = copy.deepcopy(state["participants"])
    secrets.SystemRandom().shuffle(cards)
    state.update(id=str(uuid.uuid4()), practice=practice, status="ready", cards=cards,
                 revealed=[], selected=None, winner=None, started_at=None, completed_at=None,
                 created_at=datetime.now(timezone.utc).isoformat())
    return state


def start_draw(state):
    if state["status"] == "ready":
        if not state["practice"] and datetime.fromisoformat(state["scheduled_at"]) > datetime.now(timezone.utc):
            raise DrawError("尚未到设定的抽奖时间；你可以先使用试玩模式。", 409)
        state["status"] = "active"
        state["started_at"] = datetime.now(timezone.utc).isoformat()
    return state


def update_draw(state, data):
    settings = validate_settings(data)
    if state["status"] != "ready":
        for key in ("participants", "mode", "scheduled_at"):
            if settings[key] != state[key]:
                raise DrawError("抽奖已经开始，只能修改标题、主办人和奖品，名单、模式和时间不能更改。", 409)
    if settings["participants"] != state["participants"]:
        cards = copy.deepcopy(settings["participants"])
        secrets.SystemRandom().shuffle(cards)
        state["cards"] = cards
    state.update(copy.deepcopy(settings))
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    return state


def select_card(state, index):
    if type(index) is not int or not 0 <= index < len(state["cards"]):
        raise DrawError("这张刮刮卡不存在。", 404)
    if state["status"] != "active" or index in state["revealed"]:
        raise DrawError("这张卡片目前无法选择。", 409)
    if state.get("selected") is not None and state["selected"] != index:
        raise DrawError("请先刮完已选中的卡片，再选择下一张。", 409)
    state["selected"] = index
    return state


def reveal_card(state, index):
    if type(index) is not int or not 0 <= index < len(state["cards"]):
        raise DrawError("这张刮刮卡不存在。", 404)
    # 重试同一个请求不会重复淘汰或重新选出赢家。
    if index in state["revealed"]:
        return state
    if state["status"] != "active":
        raise DrawError("请先开始抽奖，或此抽奖已经结束。", 409)
    if state.get("selected") != index:
        raise DrawError("请先选择这张卡片。", 409)
    state["revealed"].append(index)
    state["selected"] = None
    winner = None
    if state["mode"] == "instant":
        winner = state["cards"][index]
    elif len(state["revealed"]) == len(state["cards"]) - 1:
        winner = next(card for i, card in enumerate(state["cards"]) if i not in state["revealed"])
    if winner:
        state["winner"] = copy.deepcopy(winner)
        state["status"] = "completed"
        state["completed_at"] = datetime.now(timezone.utc).isoformat()
    return state


def public_state(state):
    result = copy.deepcopy(state)
    # 未被选择的卡片号码不会提前传到浏览器。
    result["cards"] = [
        {"index": i, "revealed": i in state["revealed"],
         "person": card if i in state["revealed"] or i == state.get("selected") or state["status"] == "completed" else None}
        for i, card in enumerate(state["cards"])
    ]
    return result
