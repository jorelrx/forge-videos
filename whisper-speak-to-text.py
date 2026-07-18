import whisper
import os

# Set the path to the local ffmpeg binary
ffmpeg_path = os.path.join(os.path.dirname(__file__), 'ffmpeg', 'ffmpeg-master-latest-win64-gpl', 'bin')
os.environ['PATH'] = f"{ffmpeg_path};{os.environ.get('PATH', '')}"

# Verify ffmpeg is accessible
try:
    import subprocess
    subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
    print("ffmpeg found and working")
except (subprocess.CalledProcessError, FileNotFoundError) as e:
    print(f"ERROR: ffmpeg is required but not found: {e}")
    print("Please ensure ffmpeg is installed in the ffmpeg/ffmpeg-master-latest-win64-gpl/bin directory")
    exit(1)

# Carregar o modelo
print("Loading Whisper model...")
model = whisper.load_model('small')  # Escolha o modelo desejado: tiny, base, small, medium, large

# Transcrever o áudio
print("Transcribing audio...")
result = model.transcribe('out1.wav')
                                                                                                                                                                                                                                       
# Salvar em out1.txt                                                                                                                                                                                                                  
with open('out1.txt', 'w', encoding='utf-8') as f:                                                                                                                                                                                    
    f.write(result['text'])                                                                                                                                                                                                           
                                                                                                                                                                                                                                    
print('Transcrição salva em out1.txt')                                                                                                                                                                                                
print('Conteúdo:')                                                                                                                                                                                                                    
print(result['text'])