import typing as tp

import aiogram.types as types


class WrappedInlineKeyboardMarkup(types.InlineKeyboardMarkup):
    def __init__(self, symbols_limit: int = 23, count_limit: int = 3) -> None:
        self.symbols_limit = symbols_limit
        super().__init__(row_width=count_limit)

    def add(self, *args: types.InlineKeyboardButton) -> None:
        row: tp.List[types.InlineKeyboardButton] = []
        row_len = 0

        for button in args:
            if row_len + len(button.text) <= self.symbols_limit and len(row) + 1 <= self.row_width:
                row.append(button)
                row_len += len(button.text)
            else:
                self.inline_keyboard.append(row)
                row = [button]
                row_len = len(button.text)

        self.inline_keyboard.append(row)
