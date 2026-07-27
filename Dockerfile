# TeleSpace/Dockerfile
FROM python:3.10-slim

WORKDIR /apps

RUN apt-get update && apt-get install -y git

# نسخ المتطلبات وتثبيتها
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ كامل المشروع
COPY . .

# إنشاء مجلدات للملفات الثابتة لضمان وجودها
RUN mkdir -p static/profiles static/thumbnails

# تعيين مسار البايثون ليرى المجلدات الفرعية كـ Modules
ENV PYTHONPATH=/apps