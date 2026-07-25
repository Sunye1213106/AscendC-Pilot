from pathlib import Path

path = Path('engines/understand-operator/uo/scripts/receiver_type_facts.py')
text = path.read_text(encoding='utf-8')
text = text.replace(
    'canonical_base, collect_type_aliases, expand_type_candidates, normalize_declared_type,\n',
    'canonical_base, collect_template_member_aliases, collect_type_aliases, expand_type_candidates, normalize_declared_type,\n',
)
text = text.replace(
    '    type_aliases: dict[str, set[str]] = field(default_factory=dict)\n',
    '    type_aliases: dict[str, set[str]] = field(default_factory=dict)\n    template_member_aliases: dict = field(default_factory=dict)\n',
)
text = text.replace(
    '    facts.type_aliases = collect_type_aliases(source_texts)\n',
    '    facts.type_aliases = collect_type_aliases(source_texts)\n    facts.template_member_aliases = collect_template_member_aliases(source_texts)\n',
)
text = text.replace(
    'expand_type_candidates(receiver_type, facts.type_aliases, max_depth=2)',
    'expand_type_candidates(\n        receiver_type, facts.type_aliases,\n        member_aliases=facts.template_member_aliases, max_depth=3\n    )',
)
path.write_text(text, encoding='utf-8')

# Append focused product tests.
test = Path('engines/understand-operator/tests/test_template_type_normalizer.py')
t = test.read_text(encoding='utf-8')
t = t.replace(
    'from uo.scripts.type_normalizer import collect_type_aliases, expand_type_candidates',
    'from uo.scripts.type_normalizer import (\n    collect_template_member_aliases, collect_type_aliases, expand_type_candidates\n)',
)
addition = r'''


def test_template_member_alias_substitutes_type_arguments() -> None:
    source = """
    template <typename T, bool FLAG>
    struct Selector {
      using TYPE = Buffer<T>;
    };
    """
    members = collect_template_member_aliases({'x.h': source})
    assert expand_type_candidates(
        'Selector<float,true>::TYPE', {}, member_aliases=members, max_depth=2
    ) == {'Buffer<float>'}


def test_template_member_partial_specialization_is_fail_closed() -> None:
    source = """
    template <typename T, bool FLAG> struct Selector { using TYPE = Buffer<T>; };
    template <typename T> struct Selector<T, false> { using TYPE = std::nullptr_t; };
    """
    members = collect_template_member_aliases({'x.h': source})
    assert expand_type_candidates(
        'Selector<float,false>::TYPE', {}, member_aliases=members, max_depth=2
    ) == {'Buffer<float>', 'std::nullptr_t'}
'''
if 'test_template_member_alias_substitutes_type_arguments' not in t:
    t += addition
test.write_text(t, encoding='utf-8')
