"""Registry das fontes remotas: nome -> construtor. Resolve --source (e "all")."""
from forge.knowledge.sources.remote.gutenberg import Gutenberg
from forge.knowledge.sources.remote.internet_archive import InternetArchive
from forge.knowledge.sources.remote.sep import SEP
from forge.knowledge.sources.remote.wikisource import Wikisource


def construir_fontes(nomes: list[str], *, settings) -> list:
    construtores = {
        "gutenberg": lambda: Gutenberg(),
        "internet_archive": lambda: InternetArchive(),
        "wikisource": lambda: Wikisource(settings.knowledge.wikisource_langs),
        "sep": lambda: SEP(),
    }
    if "all" in nomes:
        nomes = list(construtores)
    return [construtores[n]() for n in nomes]
