from __future__ import absolute_import, unicode_literals

OTHER = 'other'
WAIT_MESSAGE = 'wait_message'
RULES = 'rules'
CATEGORY = 'category'
BASE = 'base'
RULESET_TYPE = 'ruleset_type'
TEXT = 'text'
TEST = 'test'
STR_TRUE = 'true'
CONTAINS_ANY = 'contains_any'
TYPE = 'type'
EQ = 'eq'


def get_fb_payload(rules, text, lang):

    payload = dict(text=text)

    if rules:
        is_valid = check_rules(rules.get(RULES))
        if is_valid and rules.get(RULESET_TYPE) == WAIT_MESSAGE:

            buttons = []
            for rule in rules.get(RULES):
                category, value = get_values(rule, lang)

                if category and value:
                    buttons.append(dict(content_type=TEXT, title=category, payload=value))

            if buttons:
                payload = dict(text=text, quick_replies=buttons)

    return payload


def check_rules(rules):
    if len(rules) == 1:
        if rules[0].get(TEST).get(TEST) == STR_TRUE:
            return False

    return True


def get_values(rule, lang):
    category = rule.get(CATEGORY)
    test = rule.get(TEST).get(TEST)
    value = None
    lang = lang or BASE

    category = category.get(lang, category.get(BASE))

    allowed_types = [EQ, CONTAINS_ANY]

    if test == STR_TRUE or rule.get(TEST).get(TYPE) not in allowed_types:
        pass
    elif category.lower() != OTHER.lower():
        base = test.get(lang, test.get(BASE))
        value = base.split(' ')[0]

    category = category[:20]

    return category, value
