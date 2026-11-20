import pytest
from forge.prompts.loader import load_prompt

@pytest.mark.parametrize("name", ["tema_candidatos", "tema_juiz", "research", "queries", "plan", "write_secao", "review"])
def test_load_prompt(name):
    text = load_prompt(name)
    assert isinstance(text, str) and text.strip()

def test_research_prompt_tem_placeholder_tema():
    assert "{tema}" in load_prompt("research")
