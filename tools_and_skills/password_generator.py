
"""
title: Password Generator
author: Ken Enda
version: 0.2
description: アカウント発行用のパスワードを生成します
"""

import secrets


class Tools:
    def __init__(self):
        pass

    def generate_password(
        self,
        length: int = 8,
        count: int = 1,
        use_symbols: bool = False,
    ) -> str:
        """
        アカウント発行用のパスワードを生成します。
        英大文字・英小文字・数字を必ず各1文字以上含み、誤読しやすい文字(0 O o 1 l I |)は除外されます。

        :param length: パスワードの文字数。デフォルト8、最小6、最大32。指定がなければ10を使うこと。
        :param count: 生成する個数。デフォルト1、最大5。指定がなければ1を使うこと。
        :param use_symbols: 記号(!@#$%&*+-=?)を含めるか。デフォルトfalse。記号を含める場合は12文字以上推奨。
        :return: 生成されたパスワード文字列
        """
        # バリデーション
        try:
            length = int(length) if length else 10
            count = int(count) if count else 1
        except (TypeError, ValueError):
            length, count = 10, 1

        length = max(6, min(32, length))
        count = max(1, min(5, count))

        uppercase = "ABCDEFGHJKLMNPQRSTUVWXYZ"
        lowercase = "abcdefghijkmnpqrstuvwxyz"
        digits = "23456789"
        symbols = "!@#$%&*+-=?"

        char_groups = [uppercase, lowercase, digits]
        if use_symbols:
            char_groups.append(symbols)

        all_chars = "".join(char_groups)

        passwords = []
        for _ in range(count):
            pwd_chars = [secrets.choice(group) for group in char_groups]
            pwd_chars += [
                secrets.choice(all_chars) for _ in range(length - len(char_groups))
            ]
            for i in range(len(pwd_chars) - 1, 0, -1):
                j = secrets.randbelow(i + 1)
                pwd_chars[i], pwd_chars[j] = pwd_chars[j], pwd_chars[i]
            passwords.append("".join(pwd_chars))

        if count == 1:
            return f"生成されたパスワード: {passwords[0]}"
        else:
            lines = [f"{i+1}. {p}" for i, p in enumerate(passwords)]
            return "生成されたパスワード:\n" + "\n".join(lines)
