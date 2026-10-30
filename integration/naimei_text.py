"""Deterministic spoken-text and caption preparation; no model/API calls."""
import re

DIGITS = '零一二三四五六七八九'


def chinese_integer(value):
    value = str(value)
    if len(value) > 8 or value.startswith('0') and len(value) > 1:
        return ''.join(DIGITS[int(c)] for c in value)
    n = int(value)
    if not n:
        return DIGITS[0]
    if n >= 10000:
        high, low = divmod(n, 10000)
        return chinese_integer(str(high)) + '万' + (('零' if low < 1000 else '') + chinese_integer(str(low)) if low else '')
    result, zero = '', False
    for power, unit in [(1000, '千'), (100, '百'), (10, '十'), (1, '')]:
        digit, n = divmod(n, power)
        if digit:
            if zero:
                result += '零'
            result += DIGITS[digit] + unit
            zero = False
        elif result and n:
            zero = True
    return result[1:] if result.startswith('一十') else result


def spoken_text(text):
    text = str(text).strip()
    if not text or len(text) > 1500 or '\x00' in text:
        raise ValueError('TEXT_LENGTH_INVALID')
    for source, target in [('BGM', '背景音乐'), ('GPU', '显卡'), ('AI', '人工智能'), ('fps', '帧每秒')]:
        text = re.sub(r'(?<![A-Za-z])' + source + r'(?![A-Za-z])', target, text, flags=re.I)
    text = re.sub(r'(?<=\d)[x×](?=\d)', '乘', text, flags=re.I)
    text = re.sub(r'\d+\.\d+', lambda m: chinese_integer(m[0].split('.')[0]) + '点' + ''.join(DIGITS[int(c)] for c in m[0].split('.')[1]), text)
    text = re.sub(r'\d+', lambda m: chinese_integer(m[0]), text)
    return text


def segments(text, limit=140):
    chunks, pending = [], ''
    for item in re.findall(r'[^。！？!?；;\n]*[。！？!?；;\n]|[^。！？!?；;\n]+$', text):
        if len(pending) + len(item) > limit and pending:
            chunks.append(pending)
            pending = ''
        while len(item) > limit:
            chunks.append(item[:limit])
            item = item[limit:]
        pending += item
    if pending:
        chunks.append(pending)
    if ''.join(chunks) != text:
        raise ValueError('TEXT_PARTITION_LOSS')
    return chunks


def caption_lines(text, width=18, max_lines=3):
    """Safe text-only lines; rendering must use textContent, not innerHTML."""
    clean = re.sub(r'\s+', ' ', str(text)).strip()
    lines = [clean[i:i + width] for i in range(0, len(clean), width)]
    return '\n'.join(lines[:max_lines])
