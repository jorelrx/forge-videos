import time

import torch

# Use todos os núcleos FÍSICOS (ajuste N para o nº de cores físicos do seu processador).
# Às vezes usar só os físicos (sem hyperthreading) rende mais que o padrão.
torch.set_num_threads(8)  # ex.: 8 núcleos físicos — troque pelo seu

import soundfile as sf
from omnivoice import OmniVoice
from omnivoice.models import omnivoice as omnivoice_module
from tqdm import tqdm

NUM_STEP = 16  # menos passos de difusão = mais rápido; o mantenedor diz que 16 soa bem

# ---------------------------------------------------------------------------
# Progresso
#
# generate() não aceita callback, então instrumentamos dois pontos internos:
#   - chunk_text_punctuation(): diz em quantos pedaços o texto foi partido
#     (só é chamada quando o áudio estimado passa de audio_chunk_threshold)
#   - OmniVoice.forward(): roda exatamente uma vez por passo de difusão
# Total de passos = pedaços * NUM_STEP.
# ---------------------------------------------------------------------------
progress = {"total_chunks": 1, "bar": None}

_chunk_text_punctuation = omnivoice_module.chunk_text_punctuation


def _chunk_and_count(*args, **kwargs):
    chunks = _chunk_text_punctuation(*args, **kwargs)
    # Em lote, o nº de forwards segue o item com mais pedaços.
    progress["total_chunks"] = max(progress["total_chunks"], len(chunks))
    return chunks


_forward = OmniVoice.forward


def _forward_with_progress(self, *args, **kwargs):
    bar = progress["bar"]
    if bar is None:
        # Criada no 1º forward: aí o texto já foi partido e o total é conhecido.
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

# Carrega na CPU em float32 (fp16 é coisa de GPU; na CPU é lento ou não suportado)
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
        text=""" O restaurante está cheio, mas o silêncio é o que mais impressiona. Mesas ocupadas por grupos que não conversam, olhares fixos em telas que brilham mais do 
 que os olhos. Uma mulher ri sozinha diante de um vídeo, enquanto ao lado o marido digita algo que não é para ela. Não há vazio nas cadeiras, mas a solidão 
 preenche o ar como um gás invisível. Esta é a cena que se repete: nunca estivemos tão cercados de pessoas e tão distantes delas ao mesmo tempo.            
                                                                                                                                                            
 A hiperconectividade não eliminou a solidão; ela a disfarçou. Transformou-a em algo mais perigoso porque nos convenceu de que estamos acompanhados. Cada   
 notificação no celular é um convite para crer que alguém, em algum lugar, está pensando em nós. Mas são pensamentos em forma de algoritmo, não de          
 presença. A solidão digital não é a ausência de conexões, é a ilusão de que essas conexões bastam.                                                         
                                                                                                                                                            
 Heidegger já pressentia isso em 1935, quando escreveu que o mundo se tornaria um lugar onde qualquer acontecimento, em qualquer lugar, estaria acessível   
 com rapidez. Ele não falava de solidão, mas de um obscurecimento do mundo: quando tudo é acessível, nada mais nos toca de verdade. A técnica, para ele,    
 não era apenas uma ferramenta, mas uma forma de ser que nos afasta do que é essencial. Hoje, vemos o resultado: a acessibilidade total nos fez crer que a  
 proximidade é apenas uma questão de cliques, quando na verdade a proximidade verdadeira exige tempo, silêncios e a disposição para ser surpreendido pelo   
 outro.                                                                                                                                                     
                                                                                                                                                            
 Sherry Turkle, depois de décadas estudando nossas relações com a tecnologia, descreve um fenômeno que batizou de "estarmos sozinhos juntos". Estamos       
 fisicamente presentes, mas emocionalmente ausentes, cada um mergulhado em seu próprio universo digital. As redes sociais nos dão a sensação de pertencer a 
 um grupo, mas são grupos onde não precisamos nos expor de verdade. Podemos editar nossas vidas antes de compartilhá-las, apagar as partes feias, mostrar   
 apenas o que queremos que os outros vejam. A solidão, aqui, não é a falta de contato, mas a falta de contato autêntico.                                    
                                                                                                                                                            
 E é justamente aí que o contra-argumento mais forte se levanta: a tecnologia não nos permitiu manter laços com pessoas distantes que, de outra forma,      
 teríamos perdido? Não nos deu a chance de ver o rosto de um neto que morava em outro continente, de conversar com um amigo que se mudou para outro país?   
 Não é verdade que, para muitos, as telas foram a única janela para o mundo durante tempos de isolamento forçado?                                           
                                                                                                                                                            
 Sim, é verdade. Mas há uma diferença crucial entre manter um laço e criar a ilusão de que todos os laços são iguais. A tecnologia nos permite manter       
 contatos que de outra forma se perderiam, mas não nos ensina a criar contatos que valham a pena ser mantidos. Um abraço virtual pode ser reconfortante,    
 mas não é um abraço. Uma mensagem de "estou pensando em você" pode aquecer o coração, mas não substitui o peso de uma mão no ombro em um momento de dor. A 
 hiperconectividade nos deu a quantidade, mas não a qualidade. E a solidão, no fundo, não é uma questão de quantidade de contatos, mas de profundidade      
 deles.                                                                                                                                                     
                                                                                                                                                            
 Byung-Chul Han leva essa ideia adiante ao falar de uma sociedade onde a autoexploração se disfarça de liberdade. Vivemos em um mundo onde nos sentimos     
 obrigados a estar sempre conectados, sempre disponíveis, sempre produzindo conteúdo para ser vistos. A solidão, nesse contexto, não é a ausência de        
 pessoas, mas a ausência de um eu autêntico. Estamos tão ocupados nos apresentando para os outros que esquecemos de ser nós mesmos. O filósofo sul-coreano  
 aponta que a digitalização enfraquece a coesão da comunidade porque nos afasta do corpo, do toque, da presença física. As reuniões por videoconferência    
 nos transformam em zumbis do Zoom, sempre olhando para nosso próprio rosto na tela, sempre nos avaliando, sempre nos corrigindo. A solidão, aqui, é a      
 solidão de quem se perdeu de si mesmo.                                                                                                                     
                                                                                                                                                            
 E há ainda um outro aspecto, mais sutil: a solidão digital nos faz crer que somos os únicos responsáveis por nosso bem-estar emocional. Se estamos         
 tristes, é porque não postamos a foto certa; se estamos sozinhos, é porque não temos seguidores suficientes. A tecnologia nos vende a ideia de que a       
 felicidade é uma questão de otimização pessoal, de uma vida bem gerenciada. Mas a felicidade, como a solidão, não é um problema individual. É uma questão  
 de como nos relacionamos com o mundo e com os outros.                                                                                                      
                                                                                                                                                            
 O mais irônico é que, quanto mais nos conectamos, mais nos sentimos sozinhos. Cada like, cada compartilhamento, cada comentário é um pedaço de validação   
 que buscamos desesperadamente. Mas são pedaços que nunca formam um todo. Porque a validação verdadeira não vem de fora, mas de dentro. Não vem da          
 quantidade de curtidas, mas da qualidade das relações que construímos.                                                                                     
                                                                                                                                                            
 E é aqui que a solidão digital se revela em sua forma mais cruel: ela nos faz crer que somos os únicos sozinhos. Que todos os outros estão felizes,        
 conectados, realizados. Que somos nós que falhamos em nos adaptar a esse mundo novo. Mas a verdade é que estamos todos no mesmo barco, remando em direções 
 diferentes, mas sempre sozinhos em nossos próprios oceanos digitais.                                                                                       
                                                                                                                                                            
 O que fazer, então? Não é uma questão de abandonar a tecnologia, mas de resgatar o que ela não pode nos dar. De entender que a verdadeira conexão não é a  
 que acontece através de uma tela, mas a que acontece quando olhamos nos olhos de alguém e vemos, ali, um reflexo de nós mesmos. A solidão não é o preço da 
 hiperconectividade; é o sintoma de que estamos usando a tecnologia para preencher um vazio que só pode ser preenchido por algo que ela não pode oferecer:  
 a presença autêntica, o toque, o silêncio compartilhado.                                                                                                   
                                                                                                                                                            
 E é justamente aí que a pergunta mais incômoda se impõe: e se a solidão não for um problema a ser resolvido, mas um convite para repensarmos o que         
 realmente importa? E se, em vez de tentarmos preencher cada momento de silêncio com mais conexões, aprendêssemos a ouvir o que esse silêncio tem a nos     
 dizer? A hiperconectividade nos deu o mundo nas mãos, mas nos tirou a capacidade de nos surpreendermos com ele. Nos deu todas as respostas, mas nos tirou  
 as perguntas que realmente importam.                                                                                                                       
                                                                                                                                                            
 No final, a solidão digital não é um problema tecnológico. É um problema humano. E a solução, se é que existe uma, não está em mais conexões, mas em       
 conexões mais verdadeiras. Não está em mais tempo online, mas em mais tempo presente. Não está em mais seguidores, mas em mais pessoas com quem possamos   
 ser nós mesmos. Porque a solidão, no fundo, não é a ausência de pessoas. É a ausência de um nós que valha a pena.""",
        ref_audio="ref.wav",
        # Mantenha o ref_text: sem ele, o modelo roda o Whisper pra transcrever a
        # referência — custo extra de CPU que você não precisa pagar toda vez.
        ref_text="A vida moderna é um exercício de divisão que não começamos deliberadamente.",
        num_step=NUM_STEP,
    )

if progress["bar"] is not None:
    progress["bar"].close()

sf.write("out.wav", audio[0], 24000)
print(f"out.wav — {len(audio[0]) / 24000:.1f}s de áudio", flush=True)
