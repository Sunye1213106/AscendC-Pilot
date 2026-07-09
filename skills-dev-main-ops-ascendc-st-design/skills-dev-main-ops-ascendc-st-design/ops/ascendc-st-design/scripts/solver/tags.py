_case_tags = {}


def tag(name, value):
    _case_tags[name] = value


def get_and_reset_tags():
    global _case_tags
    tags = dict(_case_tags)
    _case_tags = {}
    return tags
