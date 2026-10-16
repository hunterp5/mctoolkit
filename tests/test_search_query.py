# This file is part of MolManager.
# Copyright (C) 2026 Hunter Picard
#
# MolManager is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MolManager is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager.  If not, see <https://www.gnu.org/licenses/>.

"""Unit tests for table search query operators."""

from __future__ import annotations

from molmanager.ui.search_query import (
    SearchCondition,
    combine_search_row_sets,
    evaluate_search_condition,
    evaluate_search_conditions,
    evaluate_search_expression,
    parse_search_condition,
    parse_search_conditions,
    parse_search_expression,
    parse_search_term_groups,
    parse_substructure_term,
    split_search_terms,
    sqlite_clause_for_condition,
    sqlite_text_match_clause,
    validate_search_text_query,
)


def test_split_search_terms():
    assert split_search_terms('"a", "b" , ,"c"') == ["a", "b", "c"]


def test_parse_search_term_groups_comma_or():
    assert parse_search_term_groups('"a", "b"|"c"') == [['"a"'], ['"b"'], ['"c"']]


def test_parse_search_term_groups_quoted_comma_inside_literal():
    assert parse_search_term_groups('"a, b"') == [['"a, b"']]


def test_parse_search_term_groups_and():
    assert parse_search_term_groups(">5 & <10") == [[">5", "<10"]]


def test_parse_search_term_groups_compound():
    assert parse_search_term_groups(">5 & <10, >=1") == [[">5", "<10"], [">=1"]]


def test_parse_search_term_groups_parens():
    assert parse_search_term_groups('"(a|b)", "c"') == [['"(a|b)"'], ['"c"']]


def test_unquoted_string_rejected():
    assert parse_search_condition("ethane", partial=True) is None
    assert validate_search_text_query("ethane", partial=True) is not None


def test_quoted_string_accepted():
    cond = parse_search_condition('"ethane"', partial=True)
    assert cond is not None and cond.op == "contains" and cond.value == "ethane"


def test_numeric_comparisons():
    assert parse_search_condition(">5", partial=True) == parse_search_condition("> 5", partial=True)
    assert evaluate_search_condition(
        "10", parse_search_condition(">5", partial=True), partial=True, case_sensitive=False
    )
    assert not evaluate_search_condition(
        "3", parse_search_condition(">5", partial=True), partial=True, case_sensitive=False
    )
    assert evaluate_search_condition(
        "3", parse_search_condition("<=3", partial=True), partial=True, case_sensitive=False
    )


def test_not_contains():
    cond = parse_search_condition('NOT "ethane"', partial=True)
    assert cond is not None and cond.op == "not_contains" and cond.value == "ethane"
    assert evaluate_search_condition("propane", cond, partial=True, case_sensitive=False)
    assert not evaluate_search_condition("methane", cond, partial=True, case_sensitive=False)


def test_empty_and_not_empty():
    empty = parse_search_condition("empty", partial=True)
    assert evaluate_search_condition("  ", empty, partial=True, case_sensitive=False)
    assert not evaluate_search_condition("x", empty, partial=True, case_sensitive=False)
    not_empty = parse_search_condition("not empty", partial=True)
    assert evaluate_search_condition("x", not_empty, partial=True, case_sensitive=False)


def test_and_or_combination_legacy_flat():
    conds = parse_search_conditions(">5, <10", partial=True)
    assert evaluate_search_conditions(
        "7", conds, match_and=False, partial=True, case_sensitive=False
    )
    assert evaluate_search_conditions(
        "12", conds, match_and=False, partial=True, case_sensitive=False
    )


def test_combine_search_row_sets_not():
    assert combine_search_row_sets([None, "not"], [{0, 1, 2}, {1}]) == {0, 2}
    assert combine_search_row_sets([None, "or", "not"], [{0, 1}, {2}, {1, 2}]) == {0}
    assert combine_search_row_sets([None, "and", "not"], [{0, 1, 2}, {0, 1}, {1}]) == {0}
    assert combine_search_row_sets([None, "and"], [{0, 1}, {1}]) == {1}
    assert combine_search_row_sets([None, "or"], [{0}, {1}]) == {0, 1}


def test_compound_and_or_expression():
    expr = parse_search_expression(">5 & <10, >=20", partial=True)
    assert evaluate_search_expression("7", expr, partial=True, case_sensitive=False)
    assert not evaluate_search_expression("15", expr, partial=True, case_sensitive=False)
    assert evaluate_search_expression("25", expr, partial=True, case_sensitive=False)


def test_quoted_and_requires_both_substrings():
    expr = parse_search_expression('"ax"&"nib"', partial=True)
    assert parse_search_term_groups('"ax"&"nib"') == [['"ax"', '"nib"']]
    assert evaluate_search_expression("axitinib", expr, partial=True, case_sensitive=False)
    assert not evaluate_search_expression("axate", expr, partial=True, case_sensitive=False)
    expr2 = parse_search_expression('"ax"&"ate"', partial=True)
    assert not evaluate_search_expression("axitinib", expr2, partial=True, case_sensitive=False)


def test_pipe_or_expression():
    expr = parse_search_expression('"eth*"|"prop*"', partial=True)
    assert evaluate_search_expression("ethane", expr, partial=True, case_sensitive=False)
    assert evaluate_search_expression("propane", expr, partial=True, case_sensitive=False)
    assert not evaluate_search_expression("methane", expr, partial=True, case_sensitive=False)


def test_wildcard_contains():
    cond = parse_search_condition('"eth*"', partial=True)
    assert evaluate_search_condition("ethane", cond, partial=True, case_sensitive=False)
    assert not evaluate_search_condition("methane", cond, partial=True, case_sensitive=False)


def test_case_sensitive_partial_contains_python():
    cond = parse_search_condition('"Foo"', partial=True)
    assert cond is not None
    assert evaluate_search_condition("xFoo", cond, partial=True, case_sensitive=True)
    assert not evaluate_search_condition("xfoo", cond, partial=True, case_sensitive=True)
    assert evaluate_search_condition("xfoo", cond, partial=True, case_sensitive=False)


def test_case_sensitive_sqlite_uses_instr_not_like():
    sql, args = sqlite_text_match_clause("Name", "Foo", partial=True, case_sensitive=True)
    assert "instr" in sql.lower()
    assert "LIKE" not in sql
    assert args == ["Foo"]
    frag = sqlite_clause_for_condition(
        "Name",
        SearchCondition("contains", "Foo"),
        partial=True,
        case_sensitive=True,
    )
    assert frag is not None
    assert "instr" in frag[0].lower()


def test_substructure_not_prefix():
    pat, neg = parse_substructure_term("NOT c1ccccc1")
    assert neg and pat == "c1ccccc1"


def test_daylight_smarts_logic_not_split_by_search_ops():
    """Daylight atom/bond logic (!, &, ,, ;) must stay one SMARTS term (not search OR/AND)."""
    assert parse_search_term_groups("[F,Cl,Br,I]") == [["[F,Cl,Br,I]"]]
    assert parse_search_term_groups("[n&H1]") == [["[n&H1]"]]
    assert parse_search_term_groups("[!C;R]") == [["[!C;R]"]]
    assert parse_search_term_groups("[c,n&H1]") == [["[c,n&H1]"]]
    assert parse_search_term_groups("[c,n;H1]") == [["[c,n;H1]"]]
    assert parse_search_term_groups("[C,c]=,#[C,c]") == [["[C,c]=,#[C,c]"]]
    assert parse_search_term_groups("*@;!:*") == [["*@;!:*"]]
    assert parse_search_term_groups("[$(*C);$(*CC)]") == [["[$(*C);$(*CC)]"]]


def test_daylight_smarts_still_allows_search_or_and():
    assert parse_search_term_groups("c1ccccc1, [OH]") == [["c1ccccc1"], ["[OH]"]]
    assert parse_search_term_groups("c1ccccc1 & [OH]") == [["c1ccccc1", "[OH]"]]
    assert parse_search_term_groups("[F,Cl]|[Br,I]") == [["[F,Cl]"], ["[Br,I]"]]
