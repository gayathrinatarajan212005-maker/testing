@echo off
python -m venv venv
call venv\Scripts\activate
pip install -r requirements.txt
python manage.py makemigrations queue_app
python manage.py migrate
python manage.py seed_demo
python manage.py test queue_app
python manage.py runserver
