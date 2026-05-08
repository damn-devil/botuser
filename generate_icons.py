from PIL import Image, ImageDraw, ImageFont
import os

def create_icon(size, filename):
    # Создаем изображение
    img = Image.new('RGB', (size, size), color='#007aff')
    draw = ImageDraw.Draw(img)
    
    # Рисуем белый круг
    margin = size // 8
    draw.ellipse([margin, margin, size-margin, size-margin], fill='white')
    
    # Рисуем символ телеграмма
    center = size // 2
    telegram_color = '#007aff'
    
    # Простой символ "T" или самолетика
    draw.text((center- size//6, center- size//6), "✈️", fill=telegram_color, font=None)
    
    # Сохраняем
    img.save(filename)
    print(f"Created {filename}")

def generate_all_icons():
    sizes = [72, 96, 128, 144, 152, 192, 384, 512]
    
    # Создаем папку если нет
    os.makedirs('static/icons', exist_ok=True)
    
    for size in sizes:
        filename = f'static/icons/icon-{size}.png'
        create_icon(size, filename)

if __name__ == '__main__':
    generate_all_icons()