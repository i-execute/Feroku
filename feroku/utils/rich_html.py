from collections import deque
from datetime import datetime, timezone
from html import escape
from html.parser import HTMLParser
from typing import Iterable, Tuple, List
from telethon.helpers import add_surrogate, del_surrogate, within_surrogate, strip_text
from telethon.tl import TLObject
from telethon.tl.types import MessageEntityBold, MessageEntityItalic, MessageEntityCode, MessageEntityPre, MessageEntityEmail, MessageEntityUrl, MessageEntityTextUrl, MessageEntityMentionName, InputMessageEntityMentionName, MessageEntityUnderline, MessageEntityStrike, MessageEntityBlockquote, MessageEntityCustomEmoji, MessageEntitySpoiler, MessageEntityFormattedDate, TypeMessageEntity
CUSTOM_EMOJIS = True
_add_surrogate = add_surrogate
_del_surrogate = del_surrogate
DATE_FORMAT = (('r', 'relative'), ('w', 'day_of_week'), ('d', 'short_date'), ('D', 'long_date'), ('t', 'short_time'), ('T', 'long_time'))

def _date_args(tag, attrs):
    try:
        if tag == 'tg-time':
            date = int(attrs['unix'])
            flags = {flag for char, flag in DATE_FORMAT if char in (attrs.get('format') or '')}
        else:
            moment = datetime.fromisoformat(attrs['date'].replace('Z', '+00:00'))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            date = int(moment.timestamp())
            flags = {flag for _, flag in DATE_FORMAT if flag.replace('_', '-') in attrs}
    except (KeyError, TypeError, ValueError):
        return None
    return {'date': date, **{flag: True for flag in flags}}

def _unix(date):
    if isinstance(date, datetime):
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        return int(date.timestamp())
    try:
        return int(date)
    except (TypeError, ValueError):
        return 0

def _date_format(entity):
    if entity.relative:
        return 'r'
    return ''.join((char for char, flag in DATE_FORMAT[1:] if getattr(entity, flag) and (not (char == 'd' and entity.long_date)) and (not (char == 't' and entity.long_time))))

class HTMLToTelegramParser(HTMLParser):

    def __init__(self):
        super().__init__()
        self.text = ''
        self.entities = []
        self._building_entities = {}
        self._open_tags = deque()
        self._open_tags_meta = deque()

    def handle_starttag(self, tag, attrs):
        self._open_tags.appendleft(tag)
        self._open_tags_meta.appendleft(None)
        attrs = dict(attrs)
        EntityType = None
        args = {}
        if tag == 'strong' or tag == 'b':
            EntityType = MessageEntityBold
        elif tag == 'em' or tag == 'i':
            EntityType = MessageEntityItalic
        elif tag in ('tg-spoiler', 'spoiler') or (tag == 'span' and attrs.get('class') == 'tg-spoiler'):
            EntityType = MessageEntitySpoiler
        elif tag in ('u', 'ins'):
            EntityType = MessageEntityUnderline
        elif tag in ('del', 's', 'strike'):
            EntityType = MessageEntityStrike
        elif tag == 'blockquote':
            EntityType = MessageEntityBlockquote
            if 'expandable' in attrs:
                args['collapsed'] = True
        elif tag == 'code':
            try:
                pre = self._building_entities['pre']
                try:
                    pre.language = attrs['class'][len('language-'):]
                except KeyError:
                    pass
            except KeyError:
                EntityType = MessageEntityCode
        elif tag == 'pre':
            EntityType = MessageEntityPre
            args['language'] = ''
        elif tag == 'a':
            try:
                url = attrs['href']
            except KeyError:
                return
            if url.startswith('mailto:'):
                url = url[len('mailto:'):]
                EntityType = MessageEntityEmail
            elif self.get_starttag_text() == url:
                EntityType = MessageEntityUrl
            else:
                EntityType = MessageEntityTextUrl
                args['url'] = del_surrogate(url)
                url = None
            self._open_tags_meta.popleft()
            self._open_tags_meta.appendleft(url)
        elif tag == 'tg-emoji':
            try:
                emoji_id = int(attrs['emoji-id'])
            except (KeyError, ValueError):
                return
            EntityType = MessageEntityCustomEmoji
            args['document_id'] = emoji_id
        elif tag in ('tg-time', 'date'):
            args = _date_args(tag, attrs)
            if args is None:
                return
            EntityType = MessageEntityFormattedDate
        elif tag == 'emoji' and CUSTOM_EMOJIS:
            try:
                EntityType = MessageEntityCustomEmoji
                args['document_id'] = int(attrs['document_id'])
            except (KeyError, ValueError):
                return
        if EntityType and tag not in self._building_entities:
            self._building_entities[tag] = EntityType(offset=len(self.text), length=0, **args)

    def handle_data(self, text):
        previous_tag = self._open_tags[0] if len(self._open_tags) > 0 else ''
        if previous_tag == 'a':
            url = self._open_tags_meta[0]
            if url:
                text = url
        for tag, entity in self._building_entities.items():
            entity.length += len(text)
        self.text += text

    def handle_endtag(self, tag):
        try:
            self._open_tags.popleft()
            self._open_tags_meta.popleft()
        except IndexError:
            pass
        entity = self._building_entities.pop(tag, None)
        if entity:
            self.entities.append(entity)

def parse(html: str) -> Tuple[str, List[TypeMessageEntity]]:
    if not html:
        return (html, [])
    parser = HTMLToTelegramParser()
    parser.feed(add_surrogate(html))
    text = strip_text(parser.text, parser.entities)
    parser.entities.reverse()
    parser.entities.sort(key=lambda entity: entity.offset)
    return (del_surrogate(text), parser.entities)
ENTITY_TO_FORMATTER = {MessageEntityBold: ('<strong>', '</strong>'), MessageEntityItalic: ('<em>', '</em>'), MessageEntityCode: ('<code>', '</code>'), MessageEntityUnderline: ('<u>', '</u>'), MessageEntityStrike: ('<del>', '</del>'), MessageEntitySpoiler: ('<tg-spoiler>', '</tg-spoiler>'), MessageEntityBlockquote: lambda e, _: ('<blockquote expandable>' if e.collapsed else '<blockquote>', '</blockquote>'), MessageEntityPre: lambda e, _: ('<pre><code class="language-{}">'.format(escape(e.language)), '</code></pre>') if e.language else ('<pre>', '</pre>'), MessageEntityEmail: lambda _, t: ('<a href="mailto:{}">'.format(escape(t)), '</a>'), MessageEntityUrl: lambda _, t: ('<a href="{}">'.format(escape(t)), '</a>'), MessageEntityTextUrl: lambda e, _: ('<a href="{}">'.format(escape(e.url)), '</a>'), MessageEntityMentionName: lambda e, _: ('<a href="tg://user?id={}">'.format(e.user_id), '</a>'), InputMessageEntityMentionName: lambda e, _: ('<a href="tg://user?id={}">'.format(getattr(e.user_id, 'user_id', '')), '</a>'), MessageEntityCustomEmoji: lambda e, _: ('<tg-emoji emoji-id="{}">'.format(e.document_id), '</tg-emoji>'), MessageEntityFormattedDate: lambda e, _: ('<tg-time unix="{}"{}>'.format(_unix(e.date), ' format="{}"'.format(_date_format(e)) if _date_format(e) else ''), '</tg-time>')}

def unparse(text: str, entities: Iterable[TypeMessageEntity]) -> str:
    if not text:
        return text
    elif not entities:
        return escape(text)
    if isinstance(entities, TLObject):
        entities = (entities,)
    text = add_surrogate(text)
    insert_at = []
    for i, entity in enumerate(entities):
        s = entity.offset
        e = entity.offset + entity.length
        delimiter = ENTITY_TO_FORMATTER.get(type(entity), None)
        if delimiter:
            if callable(delimiter):
                delimiter = delimiter(entity, text[s:e])
            insert_at.append((s, i, delimiter[0]))
            insert_at.append((e, -i, delimiter[1]))
    insert_at.sort(key=lambda t: (t[0], t[1]))
    next_escape_bound = len(text)
    while insert_at:
        at, _, what = insert_at.pop()
        while within_surrogate(text, at):
            at += 1
        text = text[:at] + what + escape(text[at:next_escape_bound]) + text[next_escape_bound:]
        next_escape_bound = at
    text = escape(text[:next_escape_bound]) + text[next_escape_bound:]
    return del_surrogate(text)
