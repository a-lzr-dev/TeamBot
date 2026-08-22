from aiogram.fsm.state import State, StatesGroup


class ActionStates(StatesGroup):
    """Состояния для работы с действиями"""

    viewing_menu = State()


class SubMenuStates(StatesGroup):
    """Состояния для работы с подменю (заказы, чаты, транспорт)"""

    viewing_orders = State()
    searching_orders = State()
    viewing_chats = State()
    searching_chats = State()
    viewing_vehicles = State()
    searching_vehicles = State()


class CarrierOrderStates(StatesGroup):
    """Состояния для заказов перевозчиков"""

    viewing_orders = State()
    searching_orders = State()


class ChatDetailsStates(StatesGroup):
    """Состояния для деталей чата"""

    viewing_messages = State()


class ReplyStates(StatesGroup):
    """Состояния для ответа на сообщения"""

    waiting_for_reply_text = State()


__all__ = [
    "ActionStates",
    "SubMenuStates",
    "CarrierOrderStates",
    "ChatDetailsStates",
    "ReplyStates",
]
