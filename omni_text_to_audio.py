import time

import torch

import soundfile as sf
from omnivoice import OmniVoice
from omnivoice.models import omnivoice as omnivoice_module
from tqdm import tqdm

torch.set_num_threads(12)  # ex.: 8 núcleos físicos
torch.set_num_interop_threads(12)  # ex.: 8 núcleos físicos

NUM_STEP = 32  # menos passos de difusão = mais rápido e qualidade reduzida; 32 é o padrão do OmniVoice, 16 é mais rápido e ainda razoável

progress = {"total_chunks": 1, "bar": None}

_chunk_text_punctuation = omnivoice_module.chunk_text_punctuation


def _chunk_and_count(*args, **kwargs):
    chunks = _chunk_text_punctuation(*args, **kwargs)
    progress["total_chunks"] = max(progress["total_chunks"], len(chunks))
    return chunks

_forward = OmniVoice.forward

def _forward_with_progress(self, *args, **kwargs):
    bar = progress["bar"]
    if bar is None:
        bar = progress["bar"] = tqdm(
            total=progress["total_chunks"] * NUM_STEP,
            desc="Gerando áudio",
            unit="passo",
        )
    output = _forward(self, *args, **kwargs)
    bar.update(1)
    return output

omnivoice_module.chunk_text_punctuation = _chunk_and_count
OmniVoice.forward = _forward_with_progress

print("Carregando modelo...", flush=True)
started = time.perf_counter()
model = OmniVoice.from_pretrained(
    "k2-fsa/OmniVoice",
    device_map="cpu",
    dtype=torch.float32,
)
print(f"Modelo carregado em {time.perf_counter() - started:.1f}s", flush=True)

# inference_mode remove a sobrecarga do autograd (mais rápido que no_grad)
with torch.inference_mode():
    audio = model.generate(
        text="""Eu começo com uma cena simples, mas contundente: alguém tenta agir como se fosse livre para escolher sem limites, mas as regras ao redor—normas sociais, expectativas de grupo, hábitos que já existem no corpo—ocupam o espaço da decisão.""",
        ref_audio="ref1.mp3",
        ref_text="A vida moderna é um exercício de divisão que não começamos deliberadamente.",
        num_step=NUM_STEP,
        speed=1.0
    )

if progress["bar"] is not None:
    progress["bar"].close()

sf.write("out.wav", audio[0], 24000)
print(f"out.wav — {len(audio[0]) / 24000:.1f}s de áudio", flush=True)
