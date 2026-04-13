#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Bot для создания стикеров с удалением фона
Работает на Termux с FFmpeg + rembg
"""

import os
import subprocess
import asyncio
import shutil
import re
from uuid import uuid4
from pathlib import Path

# Установка rembg если нет
try:
    from rembg import remove
    from PIL import Image
    REMBG_AVAILABLE = True
except ImportError:
    REMBG_AVAILABLE = False
    print("⚠️ rembg не установлен. Фон удаляться не будет.")
    print("Установи: pip install rembg")

import requests

# ==================== НАСТРОЙКИ ====================
TOKEN = "8574644015:AAFJe8tVgLp75f4QVVZxEL2og8uGiBAF5RU"
ADMIN_ID = 7546928092  # Твой Telegram ID
# ==================================================

API_URL = f"https://api.telegram.org/bot{TOKEN}"
LAST_UPDATE_ID = 0
user_data = {}

def send_message(chat_id, text, keyboard=None):
    """Отправка сообщения"""
    url = f"{API_URL}/sendMessage"
    data = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'Markdown'
    }
    if keyboard:
        data['reply_markup'] = keyboard
    
    try:
        response = requests.post(url, json=data, timeout=30)
        return response.json()
    except Exception as e:
        print(f"Ошибка отправки: {e}")
        return None

def edit_message(chat_id, message_id, text, keyboard=None):
    """Редактирование сообщения"""
    url = f"{API_URL}/editMessageText"
    data = {
        'chat_id': chat_id,
        'message_id': message_id,
        'text': text,
        'parse_mode': 'Markdown'
    }
    if keyboard:
        data['reply_markup'] = keyboard
    
    try:
        response = requests.post(url, json=data, timeout=30)
        return response.json()
    except Exception as e:
        print(f"Ошибка редактирования: {e}")
        return None

def create_keyboard(buttons):
    """Создание inline клавиатуры"""
    keyboard = {
        'inline_keyboard': [[{'text': text, 'callback_data': data} for text, data in row] 
                           for row in buttons]
    }
    return keyboard

def download_file(file_id, save_path):
    """Скачивание файла"""
    try:
        get_file_url = f"{API_URL}/getFile"
        response = requests.post(get_file_url, json={'file_id': file_id}, timeout=30)
        
        if response.status_code == 200:
            file_path = response.json().get('result', {}).get('file_path')
            if file_path:
                download_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
                file_response = requests.get(download_url, timeout=60)
                
                if file_response.status_code == 200:
                    with open(save_path, 'wb') as f:
                        f.write(file_response.content)
                    return True
        return False
    except Exception as e:
        print(f"Ошибка скачивания: {e}")
        return False

def remove_video_background(input_video, output_video):
    """
    Удаление фона из видео
    
    Алгоритм:
    1. Разбиваем видео на кадры (PNG с прозрачностью)
    2. Для каждого кадра удаляем фон через rembg
    3. Собираем обработанные кадры обратно в видео
    """
    temp_dir = os.path.dirname(input_video) + f"/frames_{uuid4().hex[:8]}"
    os.makedirs(temp_dir, exist_ok=True)
    
    try:
        # 1. Извлекаем кадры из видео в PNG (сохраняем прозрачность)
        extract_cmd = [
            'ffmpeg',
            '-i', input_video,
            '-vf', 'fps=30',  # 30 FPS для стикеров
            '-pix_fmt', 'rgba',  # Сохраняем альфа-канал
            '-y',
            f'{temp_dir}/frame_%04d.png'
        ]
        
        result = subprocess.run(extract_cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print(f"FFmpeg extract error: {result.stderr}")
            return False
        
        # Получаем список кадров
        frames = sorted([f for f in os.listdir(temp_dir) if f.endswith('.png')])
        
        if not frames:
            print("Нет извлеченных кадров")
            return False
        
        print(f"Обработка {len(frames)} кадров...")
        
        # 2. Обрабатываем каждый кадр через rembg
        processed_frames_dir = f"{temp_dir}/processed"
        os.makedirs(processed_frames_dir, exist_ok=True)
        
        for i, frame in enumerate(frames):
            input_frame = os.path.join(temp_dir, frame)
            output_frame = os.path.join(processed_frames_dir, frame)
            
            try:
                # Открываем изображение
                with open(input_frame, 'rb') as img_file:
                    img_data = img_file.read()
                
                # Удаляем фон через rembg
                output_data = remove(img_data)
                
                # Сохраняем результат
                with open(output_frame, 'wb') as out_file:
                    out_file.write(output_data)
                
                if (i + 1) % 10 == 0:
                    print(f"Обработано {i + 1}/{len(frames)} кадров")
                    
            except Exception as e:
                print(f"Ошибка обработки кадра {frame}: {e}")
                # Копируем оригинал если ошибка
                shutil.copy2(input_frame, output_frame)
        
        # 3. Собираем обработанные кадры обратно в видео
        assemble_cmd = [
            'ffmpeg',
            '-framerate', '30',
            '-i', f'{processed_frames_dir}/frame_%04d.png',
            '-c:v', 'libvpx-vp9',
            '-b:v', '500k',
            '-pix_fmt', 'yuva420p',  # Сохраняем прозрачность для WebM
            '-an',  # Без звука
            '-y',
            output_video
        ]
        
        result = subprocess.run(assemble_cmd, capture_output=True, text=True, timeout=60)
        
        if result.returncode != 0:
            print(f"FFmpeg assemble error: {result.stderr}")
            return False
        
        return True
        
    except Exception as e:
        print(f"Ошибка удаления фона: {e}")
        return False
    finally:
        # Очищаем временные файлы
        shutil.rmtree(temp_dir, ignore_errors=True)

def convert_video_to_sticker(input_path, output_path, remove_bg=False):
    """Конвертация видео в стикер с опциональным удалением фона"""
    try:
        # Если нужно удалить фон - делаем это отдельно
        if remove_bg and REMBG_AVAILABLE:
            temp_video = output_path.replace('.webm', '_temp.mp4')
            
            # Сначала конвертируем в MP4 с правильным размером
            convert_cmd = [
                'ffmpeg',
                '-i', input_path,
                '-t', '3',
                '-vf', f'scale=512:512:force_original_aspect_ratio=1:flags=lanczos,pad=512:512:(ow-iw)/2:(oh-ih)/2',
                '-c:v', 'libx264',
                '-pix_fmt', 'rgba',
                '-an',
                '-y',
                temp_video
            ]
            
            result = subprocess.run(convert_cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                return False
            
            # Удаляем фон
            success = remove_video_background(temp_video, output_path)
            os.unlink(temp_video)
            return success
        else:
            # Обычная конвертация без удаления фона
            cmd = [
                'ffmpeg',
                '-i', input_path,
                '-t', '3',
                '-vf', f'scale=512:512:force_original_aspect_ratio=1:flags=lanczos,pad=512:512:(ow-iw)/2:(oh-ih)/2',
                '-c:v', 'libvpx-vp9',
                '-b:v', '300k',
                '-speed', '4',
                '-an',
                '-f', 'webm',
                '-y',
                output_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return result.returncode == 0 and os.path.exists(output_path)
            
    except Exception as e:
        print(f"FFmpeg ошибка: {e}")
        return False

def upload_sticker_file(user_id, sticker_path):
    """Загрузка стикера для создания стикерпака"""
    url = f"{API_URL}/uploadStickerFile"
    try:
        with open(sticker_path, 'rb') as f:
            files = {'sticker': f}
            data = {
                'user_id': user_id,
                'sticker_format': 'video'
            }
            response = requests.post(url, data=data, files=files, timeout=60)
            if response.status_code == 200:
                return response.json().get('result', {}).get('file_id')
        return None
    except Exception as e:
        print(f"Ошибка загрузки: {e}")
        return None

def create_sticker_set(user_id, pack_name, pack_title, sticker_file_id):
    """Создание стикерпака"""
    url = f"{API_URL}/createNewStickerSet"
    data = {
        'user_id': user_id,
        'name': pack_name,
        'title': pack_title,
        'stickers': [{
            'sticker': sticker_file_id,
            'emoji_list': ['🎬'],
            'format': 'video'
        }]
    }
    
    try:
        response = requests.post(url, json=data, timeout=30)
        return response.status_code == 200
    except Exception as e:
        print(f"Ошибка создания: {e}")
        return False

def send_sticker(chat_id, sticker_file):
    """Отправка стикера"""
    url = f"{API_URL}/sendSticker"
    try:
        with open(sticker_file, 'rb') as f:
            files = {'sticker': f}
            data = {'chat_id': chat_id}
            response = requests.post(url, data=data, files=files, timeout=60)
            return response.json()
    except Exception as e:
        print(f"Ошибка отправки стикера: {e}")
        return None

def cleanup_user_data(chat_id):
    """Очистка временных файлов"""
    if chat_id in user_data:
        temp_dir = user_data[chat_id].get('temp_dir')
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        del user_data[chat_id]

def process_updates():
    """Обработка обновлений"""
    global LAST_UPDATE_ID
    
    url = f"{API_URL}/getUpdates"
    params = {
        'offset': LAST_UPDATE_ID + 1,
        'timeout': 30,
        'allowed_updates': ['message', 'callback_query']
    }
    
    try:
        response = requests.get(url, params=params, timeout=35)
        if response.status_code == 200:
            updates = response.json().get('result', [])
            
            for update in updates:
                LAST_UPDATE_ID = update['update_id']
                
                # Обработка сообщений
                if 'message' in update:
                    message = update['message']
                    chat_id = message['chat']['id']
                    
                    if chat_id != ADMIN_ID:
                        send_message(chat_id, "❌ Бот доступен только создателю")
                        continue
                    
                    # Команды
                    if 'text' in message:
                        text = message['text']
                        
                        if text == '/start':
                            user_data[chat_id] = {'state': 'waiting_video'}
                            send_message(
                                chat_id,
                                "🎬 *Бот для создания стикеров с удалением фона*\n\n"
                                "Отправь мне видео (до 3 секунд)\n\n"
                                "Форматы: MP4, MOV, GIF\n"
                                "Команды:\n/start - начать\n/cancel - отменить"
                            )
                        elif text == '/cancel':
                            cleanup_user_data(chat_id)
                            user_data[chat_id] = {'state': 'waiting_video'}
                            send_message(chat_id, "❌ Отменено. Используй /start")
                        else:
                            state = user_data.get(chat_id, {}).get('state', 'waiting_video')
                            
                            if state == 'waiting_pack_name':
                                handle_pack_name(chat_id, text)
                            elif state == 'waiting_pack_title':
                                handle_pack_title(chat_id, text)
                    
                    # Обработка видео
                    elif 'video' in message:
                        state = user_data.get(chat_id, {}).get('state', 'waiting_video')
                        if state == 'waiting_video':
                            file_id = message['video']['file_id']
                            duration = message['video'].get('duration', 10)
                            
                            if duration > 3:
                                send_message(chat_id, f"❌ Видео слишком длинное ({duration} сек). Нужно до 3 секунд")
                            else:
                                handle_video(chat_id, file_id, message['message_id'])
                        else:
                            send_message(chat_id, "❌ Сначала заверши текущую операцию или отправь /cancel")
                    
                    elif 'animation' in message:
                        file_id = message['animation']['file_id']
                        handle_video(chat_id, file_id, message['message_id'])
                
                # Обработка callback запросов
                elif 'callback_query' in update:
                    callback = update['callback_query']
                    chat_id = callback['message']['chat']['id']
                    message_id = callback['message']['message_id']
                    data = callback['data']
                    
                    if chat_id == ADMIN_ID:
                        handle_callback(chat_id, message_id, data)
                        
                        answer_url = f"{API_URL}/answerCallbackQuery"
                        requests.post(answer_url, json={'callback_query_id': callback['id']})
    
    except requests.exceptions.Timeout:
        print("Таймаут, продолжаем...")
    except Exception as e:
        print(f"Ошибка: {e}")

def handle_video(chat_id, file_id, message_id):
    """Обработка видео - показываем выбор удаления фона"""
    user_data[chat_id] = {
        'state': 'waiting_bg_choice',
        'file_id': file_id,
        'message_id': message_id
    }
    
    keyboard = create_keyboard([
        [("✅ Да, удалить фон", "remove_bg"), ("❌ Нет, оставить", "keep_bg")],
        [("⏭️ Пропустить этот шаг", "keep_bg")]
    ])
    
    edit_message(
        chat_id,
        message_id,
        "📹 Видео получено!\n\n🎨 Нужно ли удалить фон? (может занять 30-60 секунд)",
        keyboard
    )

def handle_callback(chat_id, message_id, choice):
    """Обработка выбора удаления фона"""
    data = user_data.get(chat_id, {})
    
    if data.get('state') != 'waiting_bg_choice':
        return
    
    remove_bg = (choice == 'remove_bg')
    
    edit_message(
        chat_id,
        message_id,
        "🔄 Обрабатываю видео...\n\n" + 
        ("🎨 Удаляю фон (это может занять до минуты)..." if remove_bg else "📦 Конвертирую в стикер...")
    )
    
    # Создаем временные файлы
    temp_dir = f"/tmp/sticker_{chat_id}_{uuid4().hex[:8]}"
    os.makedirs(temp_dir, exist_ok=True)
    
    input_path = f"{temp_dir}/input.mp4"
    output_path = f"{temp_dir}/sticker.webm"
    
    # Скачиваем видео
    if download_file(data['file_id'], input_path):
        # Конвертируем с удалением фона если нужно
        if convert_video_to_sticker(input_path, output_path, remove_bg):
            # Проверяем размер
            size = os.path.getsize(output_path)
            if size > 256 * 1024:
                edit_message(chat_id, message_id, f"⚠️ Стикер {size/1024:.0f}KB, сжимаю...")
            
            user_data[chat_id] = {
                'sticker_path': output_path,
                'temp_dir': temp_dir,
                'state': 'waiting_pack_name'
            }
            
            # Отправляем готовый стикер
            send_sticker(chat_id, output_path)
            
            keyboard = create_keyboard([
                [("✅ Создать стикерпак", "create_pack")],
                [("❌ Отмена", "cancel")]
            ])
            
            send_message(
                chat_id,
                "✨ Стикер готов!\n\nХочешь создать стикерпак?",
                keyboard
            )
        else:
            edit_message(chat_id, message_id, "❌ Ошибка конвертации. Попробуй другое видео")
            cleanup_user_data(chat_id)
            user_data[chat_id] = {'state': 'waiting_video'}
    else:
        edit_message(chat_id, message_id, "❌ Ошибка скачивания. Попробуй еще раз")
        cleanup_user_data(chat_id)
        user_data[chat_id] = {'state': 'waiting_video'}

def handle_pack_name(chat_id, pack_name):
    """Обработка названия стикерпака"""
    if not re.match(r'^[a-zA-Z0-9_]+$', pack_name):
        send_message(chat_id, "❌ Неверное название. Только латиница, цифры и _\nПопробуй еще раз:")
        return
    
    full_name = f"{pack_name}_by_animated_sticksbot"
    user_data[chat_id]['pack_name'] = full_name
    user_data[chat_id]['state'] = 'waiting_pack_title'
    
    send_message(chat_id, "📝 Введи название стикерпака (как будет отображаться):\nПример: 'Мои крутые стикеры'")

def handle_pack_title(chat_id, title):
    """Создание стикерпака"""
    data = user_data.get(chat_id, {})
    pack_name = data.get('pack_name')
    sticker_path = data.get('sticker_path')
    
    if not pack_name or not sticker_path:
        send_message(chat_id, "❌ Ошибка. Начни заново с /start")
        cleanup_user_data(chat_id)
        return
    
    send_message(chat_id, "🚀 Создаю стикерпак...")
    
    sticker_file_id = upload_sticker_file(chat_id, sticker_path)
    
    if sticker_file_id:
        if create_sticker_set(chat_id, pack_name, title, sticker_file_id):
            sticker_url = f"https://t.me/addstickers/{pack_name}"
            send_message(
                chat_id,
                f"🎉 *Стикерпак создан!*\n\n"
                f"📦 Название: `{pack_name}`\n"
                f"🔗 [Добавить стикеры]({sticker_url})\n\n"
                f"Отправь /start чтобы создать еще",
                None
            )
        else:
            send_message(chat_id, "❌ Ошибка создания. Возможно такое имя уже существует")
    else:
        send_message(chat_id, "❌ Ошибка загрузки стикера")
    
    cleanup_user_data(chat_id)

def main():
    """Запуск бота"""
    print("🎬 Запуск бота для создания стикеров")
    print(f"Бот: @animated_sticksbot")
    print(f"Админ: {ADMIN_ID}")
    print("=" * 40)
    
    # Проверка FFmpeg
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        print("✅ FFmpeg готов")
    except:
        print("❌ Установи FFmpeg: pkg install ffmpeg")
        return
    
    # Проверка rembg
    if REMBG_AVAILABLE:
        print("✅ rembg установлен - фон будет удаляться")
    else:
        print("⚠️ rembg НЕ установлен - фон удаляться не будет")
        print("  Установи: pip install rembg onnxruntime")
    
    print("\n✅ Бот запущен и ждет сообщения...")
    print("Нажми Ctrl+C для остановки\n")
    
    while True:
        try:
            process_updates()
        except KeyboardInterrupt:
            print("\n👋 Остановка бота...")
            break
        except Exception as e:
            print(f"Ошибка в цикле: {e}")
            import time
            time.sleep(5)

if __name__ == '__main__':
    main()
