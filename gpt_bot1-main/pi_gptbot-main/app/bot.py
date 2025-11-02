import os
import time
import logging
import argparse
import RPi.GPIO as GPIO
import textwrap
import re
import sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

# New imports for Google STT + gTTS TTS
import speech_recognition as sr
from gtts import gTTS
import tempfile
import subprocess

# Translations
trans_hu = {"listening" : "FÜLEL", "thinking" : "GONDOL", "speaking" : "BESZÉL", "silent":"CSENDBEN", "lang": "Hungarian"}
trans_en = {"listening" : "LISTENING", "thinking" : "THINKING", "speaking" : "SPEAKING", "silent":"SILENT", "lang": "English"}
trans_de = {"listening" : "HÖREN", "thinking" : "DENKEN", "speaking" : "SPRECHEN", "silent":"STILL", "lang": "German"}
translation = {}
translation["hu"] = trans_hu
translation["en"] = trans_en
translation["de"] = trans_de

lang_switch_phrases = [
    {"language": "English", 
        "voice": "en-GB-HollieNeural", 
        "phrases": ["válts angolra", "beszélj angolul", "válaszolj angolul", "angolul válaszolj", "angolul beszélj"]},
    {"language": "Hungarian", 
        "voice": "hu-HU-NoemiNeural", 
        "phrases": ["switch to hungarian", "respond in hungarian", "use hungarian", "talk in hungarian", "talk hungarian", "speak in hungarian", "speak hungarian"]},
    {"language": "German", 
        "voice": "de-DE-KatjaNeural", 
        "phrases": ["válts németre", "beszélj németül", "válaszolj németül", "németül válaszolj", "németül beszélj", "switch to german", "respond in german", "use german", "talk in german", "talk german", "speak in german", "speak german"]  }
]

# Local classes
from utils import Utils
utils = Utils()

from botconfig import BotConfig
bot_config = BotConfig()

from gptchatservice import GPTChatService

HEADLESS = True  # <-- set True when running without LCD display

if not HEADLESS:
    from lcdservice import LCDServiceColor
    lcd_service = LCDServiceColor()
else:
    class DummyLCD:
        def draw_face(self, *a, **kw): pass
        def draw_large_icon(self, *a, **kw): pass
        def clear_screen(self): pass
    lcd_service = DummyLCD()


# Audio HW settings
output_device_name="sysdefault:CARD=UACDemoV10"
input_device_name="hw:CARD=WEBCAM"
mute_mic_during_tts = True

# Globals for new STT/TTS
recognizer = None
microphone = None
background_listener = None  # function to stop background listening
speech_lang = "hu"
speech_voice = "hu-HU-NoemiNeural"
ui_lang = "hu"

# Global variable for stopping execution
done = False 
listening = True
thinking = False
speaking = False

# Statistics
total_tts_duration = 0
total_stt_chars = 0
program_start_time = 0

# Utility: check patterns like "a." single char dot
def check_single_char_dot(string):
    pattern = r'^[a-zA-Z0-9]\.'
    match = re.search(pattern, string)
    if match:
        return True
    else:
        return False

# Centralized processing of recognized text (used by Google callback)
def process_recognized_text(stt_text):
    try:
        global thinking
        global speaking
        global total_stt_chars

        if stt_text is None:
            return

        # ignore if currently speaking or thinking
        if (speaking == True or thinking == True):
            return

        if stt_text == "" or check_single_char_dot(stt_text): 
            return

        recognized_text_log = f"Recognized speech: {stt_text}"
        print(recognized_text_log, flush=True)
        log.info(recognized_text_log)

        total_stt_chars += len(stt_text)

        if (mute_mic_during_tts): utils.mute_mic(device_name=input_device_name)
        
        if (bot_config.change_face == True):
            change_mood_thinking(stt_text)
           
        thinking = True
        start = time.time()

        if (bot_config.exp_lang_autoswitch == True):
            lang_switcher = check_lang_switch_phrases(stt_text)
            if (lang_switcher != None):
                change_language(lang_switcher)
                print(f"Language switched to {lang_switcher['language']}")
                log.info(f"Language switched to {lang_switcher['language']}")
                stt_text = f" From now on, you will have to respond in {lang_switcher['language']}! So please respond in {lang_switcher['language']}. Acknowledge this by saying that you will speak now in {lang_switcher['language']}"

        response_text = gpt_service.ask(stt_text)
        openai_call_duration = f'OpenAI API call ended: {time.time() - start} ms'
        print(openai_call_duration, flush=True)
        log.debug(openai_call_duration)
        thinking = False
        
        if (bot_config.change_face == True):
            change_mood_talking(response_text)
            time.sleep(0.5) 
        
        start = time.time()
        speak_text(response_text)

        if (listening == False):
            return
        
        print("Speak!")
        if (bot_config.auto_mute_mic == True): 
            toggle_mute(False)
        else:
            toggle_mute(True)
            
    except Exception as e:
        log.error(e)
        if hasattr(e, 'message'):
            print(e.message)
            log.error(e.message)
        else:
            print(e)          
        return "" 

# Google SpeechRecognition callback
def google_stt_callback(recognizer_obj, audio):
    """Callback used by listen_in_background. Runs in a separate thread."""
    try:
        # Use Google Web Speech API (online) — good for accuracy and lighter on Pi
        text = recognizer_obj.recognize_google(audio, language=speech_lang)
        # pass to main processing function
        process_recognized_text(text)
    except sr.UnknownValueError:
        # speech was unintelligible
        return
    except sr.RequestError as e:
        # API was unreachable or unresponsive
        log.error(f"Could not request results from Google Speech Recognition service; {e}")
        return
    except Exception as e:
        log.error(f"Google STT callback error: {e}")
        return

def change_mood_thinking(top_text):
    wrapper = textwrap.TextWrapper(width=70)
    text_wrapped = wrapper.fill(text=top_text)
    if (bot_config.show_recognized == False): 
        text_wrapped = ''
    lcd_service.draw_face(face=LCDServiceColor.FACE_THINK, icon=LCDServiceColor.ICON_LOAD, additional_text=translation[ui_lang]['thinking'], top_small_text=text_wrapped)

def change_mood_talking(top_text):
    wrapper = textwrap.TextWrapper(width=70)
    text_wrapped = wrapper.fill(text=top_text)
    if (bot_config.show_gpt_response == False):
        text_wrapped = ''    
    lcd_service.draw_face(face=LCDServiceColor.FACE_TALK, icon=LCDServiceColor.ICON_SPEAKER, additional_text=translation[ui_lang]['speaking'], top_small_text=text_wrapped)

def escape( str_xml: str ):
    str_xml = str_xml.replace("&", "&amp;")
    str_xml = str_xml.replace("<", "&lt;")
    str_xml = str_xml.replace(">", "&gt;")
    str_xml = str_xml.replace("\"", "&quot;")
    str_xml = str_xml.replace("'", "&apos;")
    return str_xml       

def speak_text(text):
    """
    Use gTTS to synthesize speech, save to a temporary mp3, play with mpg123 (must be installed),
    and delete the temp file after playing.
    """
    global speaking
    global total_tts_duration

    if text is None or text.strip() == "":
        return

    speaking = True
    try:
        # Map speech_lang (like 'hu' or 'en') to gTTS language codes
        # speech_lang is e.g. 'hu' or 'en' or 'de' from voice config
        gtts_lang = speech_lang if len(speech_lang) == 2 else speech_lang[0:2]

        # gTTS may not support every language variant; fallback if needed
        try:
            tts = gTTS(text=text, lang=gtts_lang)
        except Exception as e:
            log.warning(f"gTTS init failed for lang {gtts_lang}: {e}. Falling back to 'en'.")
            tts = gTTS(text=text, lang='en')

        tmpf = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
        tmpf_name = tmpf.name
        tmpf.close()
        tts.save(tmpf_name)

        # play using mpg123 (quiet)
        # ensure mpg123 is installed on the system: sudo apt-get install -y mpg123
        play_start = time.time()
        try:
            subprocess.run(['mpg123', '-q', tmpf_name], check=True)
        except FileNotFoundError:
            log.error("mpg123 not found. Please install mpg123 or change playback method.")
            # try with aplay (works for wav only), so warn if mpg123 missing
        play_end = time.time()

        # Update total_tts_duration with playback time
        duration = play_end - play_start
        total_tts_duration += duration

        print(f"AI response (played ~{duration:.2f}s): {text}")
    except Exception as e:
        log.error(f"TTS error: {e}")
    finally:
        speaking = False
        # cleanup temp file
        try:
            if os.path.exists(tmpf_name):
                os.remove(tmpf_name)
        except:
            pass

# Unregister / stop background listening
def unset_speech_recognizer_events():
    global background_listener
    if background_listener is not None:
        try:
            background_listener(wait_for_stop=False)  # call returned stop function with wait_for_stop=False to stop immediately
        except Exception:
            pass
        background_listener = None

# Register speech recognizer events / start background listener
def set_speech_recognizer_events():
    global recognizer, microphone, background_listener, listening

    if recognizer is None or microphone is None:
        return

    # Start background listening; this returns a function to stop listening
    # use phrase_time_limit if needed, otherwise continuous streaming to callback
    try:
        background_listener = recognizer.listen_in_background(microphone, google_stt_callback, phrase_time_limit=None)
        listening = True
    except Exception as e:
        log.error(f"Failed to start background listener: {e}")
        background_listener = None

def run_ai():

    log.info("Started bot...")

    global program_start_time

    # Start continuous speech recognition
    if (mute_mic_during_tts): utils.unmute_mic(device_name=input_device_name)

    program_start_time = time.time()
  
    if (bot_config.auto_mute_mic == True): 
        toggle_mute(False)
    else:
        print("Speak!")
        lcd_service.draw_face(face=LCDServiceColor.FACE_LISTEN, icon=LCDServiceColor.ICON_MIC, additional_text=translation[ui_lang]['listening'])

    while not done:
        time.sleep(.5)

def init_logging():
    global log
    log = logging.getLogger("bot_log")
    logging.basicConfig(filename='gpt_service.log', level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

def check_internet():
        
    if (utils.has_internet() == True):
        return
        
    time.sleep(1)

    while not utils.has_internet():
        lcd_service.draw_large_icon(LCDServiceColor.ICON_ERROR, "Waiting for internet connect...")
        time.sleep(1)
    
    lcd_service.draw_large_icon(LCDServiceColor.ICON_WIFI, "Internet connection found!")
    time.sleep(1)
    lcd_service.clear_screen()    

def check_lang_switch_phrases(input_text):
    for phrase_item in lang_switch_phrases:
        for phrase_text in phrase_item["phrases"]:
            if re.search(phrase_text, input_text, re.IGNORECASE):
                lang_switcher = {"language": phrase_item["language"], "voice": phrase_item["voice"]}
                return lang_switcher
    return None

def change_language(lang_switcher):
    change_voice(lang_switcher["voice"])
    gpt_service.change_language(lang_switcher["language"])


def change_voice(voice_name):
    """
    Update language settings derived from a 'voice name' string and restart recognizer.
    """
    unset_speech_recognizer_events()

    global speech_voice
    global speech_lang
    global ui_lang
    global recognizer, microphone

    speech_voice = voice_name
    # first 5 chars like 'hu-HU' -> take 'hu' for gTTS and Google (language code)
    speech_lang = speech_voice[0:2].lower()
    ui_lang = speech_voice[0:2]

    # (re)create recognizer and microphone with updated language if necessary
    recognizer = sr.Recognizer()
    # microphone may optionally specify device index; use default Microphone
    try:
        microphone = sr.Microphone()  # you could pass device_index if needed
    except Exception as e:
        log.error(f"Failed to initialize microphone: {e}")
        microphone = None

    set_speech_recognizer_events()

def init_speech_google(voice_name):
    """
    Initialize the speech stack using SpeechRecognition (Google) and gTTS.
    """
    global speech_voice, speech_lang, ui_lang, recognizer, microphone, background_listener

    speech_voice = voice_name
    speech_lang = speech_voice[0:2].lower()
    ui_lang = speech_voice[0:2]

    # speech rate / pitch still pulled from bot_config but gTTS doesn't support direct rate/pitch.
    # Keep the values for UI and future optional TTS engines.
    global speech_rate
    global speech_pitch
    speech_rate = bot_config.rate
    speech_pitch = bot_config.pitch

    # Initialize recognizer and microphone
    recognizer = sr.Recognizer()
    try:
        # adjust for ambient noise
        microphone = sr.Microphone()
        with microphone as source:
            recognizer.adjust_for_ambient_noise(source, duration=1.0)
    except Exception as e:
        log.error(f"Microphone initialization failed: {e}")
        microphone = None

    # Start background listening
    set_speech_recognizer_events()

def init_gpio():
    GPIO.setmode(GPIO.BCM) # Use physical pin numbering
    GPIO.setup(15, GPIO.IN, pull_up_down=GPIO.PUD_DOWN) # Set pin 15 as input
    GPIO.add_event_detect(15,GPIO.RISING,callback=button_pushed, bouncetime=500) # Setup event on pin 15 rising edge
    

def button_pushed(channel):

    global thinking
    if (thinking == True):
        return
    
    global listening
    listening = not listening
    toggle_mute(listening)

def toggle_mute(listening_local):
    """
    Start/stop recognition according to listening_local. Also handle mic mute and TTS stop.
    """
    global recognizer, microphone, background_listener, listening

    if (listening_local == True):
        listening = True
        if (bot_config.change_face == True):
            lcd_service.draw_face(face=LCDServiceColor.FACE_LISTEN, icon=LCDServiceColor.ICON_MIC, additional_text=translation[ui_lang]['listening'])
        if (mute_mic_during_tts): utils.unmute_mic(device_name=input_device_name)
        # start background listener if not started
        if background_listener is None and recognizer is not None and microphone is not None:
            set_speech_recognizer_events()
    if (listening_local == False):
        listening = False
        if (bot_config.change_face == True):
            lcd_service.draw_face(face=LCDServiceColor.FACE_SILENT, icon=LCDServiceColor.ICON_MIC_OFF, additional_text=translation[ui_lang]['silent'])  
        if (mute_mic_during_tts): utils.mute_mic(device_name=input_device_name)
        # stop background listening
        unset_speech_recognizer_events()

def init_ai():
    global gpt_service
    gpt_service = GPTChatService(translation[ui_lang]['lang'])
    print(translation[ui_lang]['lang'])

def end_program(write_stats = True):

    lcd_service.clear_screen()
    GPIO.cleanup()     

    if (write_stats):
        global gpt_service
        global program_start_time
        global total_stt_chars
        global total_tts_duration

        program_end_time = time.time()
        program_run_duration = program_end_time - program_start_time
        print(f'STATS: program duration: {program_run_duration} seconds')
        print(f'STATS: total TTS duration: {total_tts_duration} sec')
        print(f'STATS: total STT characters: {total_stt_chars} chars')    
        print(f'STATS: total OpenAI API tokens: {gpt_service.get_stats()}')        
    


def main():
    try:
        init_gpio()
        init_logging()
        check_internet()
        # Initialize Google STT + gTTS stack
        init_speech_google(bot_config.voice_name)        
        init_ai()        
        run_ai() 
    except KeyboardInterrupt:
        end_program()   
    finally:
        end_program()       
    
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--audio_input", help='Audio input device')
    parser.add_argument("-o", "--audio_output", help='Audio output device')
    parser.add_argument("-r", "--record_card", help='Audio record card')
    args = parser.parse_args()
    if (args.audio_input is not None):
        input_device_name=args.audio_input
        print(f"Audio input override: {input_device_name}")
    if (args.audio_output is not None):
        output_device_name=args.audio_output  
        print(f"Audio output override: {output_device_name}")  
        
    main()
