#!/usr/bin/env python3
import sys
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from db.models import Base, User, UserRole

def create_db_and_add_superadmin(tg_id, username, port, login):
    """Создание таблиц в базе данных и добавление суперадмина"""
    from config.settings import DATABASE_URL
    
    print(f"Подключение к базе данных: {DATABASE_URL}")
    
    # Подключение к базе данных
    engine = create_engine(DATABASE_URL)
    
    # Создание всех таблиц
    print("Создание таблиц в базе данных...")
    Base.metadata.create_all(engine)
    print("Таблицы успешно созданы")
    
    # Создание сессии
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        # Проверка, существует ли пользователь с таким tg_id
        existing_user = session.query(User).filter(User.tg_id == tg_id).first()
        if existing_user:
            print(f"Пользователь с tg_id {tg_id} уже существует!")
            # Обновляем роль до суперадмина
            existing_user.role = UserRole.SUPERADMIN
            session.commit()
            print(f"Роль пользователя обновлена до SUPERADMIN")
            return
        
        # Создание нового пользователя с ролью суперадмин
        subscription_until = datetime.datetime.now() + datetime.timedelta(days=365)  # Подписка на год
        new_user = User(
            tg_id=tg_id,
            username=username,
            role=UserRole.SUPERADMIN,
            port=port,
            login=login,
            subscription_until=subscription_until
        )
        
        session.add(new_user)
        session.commit()
        print(f"Суперадмин успешно добавлен: {username} (ID: {tg_id})")
    
    except Exception as e:
        session.rollback()
        print(f"Ошибка при добавлении суперадмина: {e}")
    
    finally:
        session.close()

if __name__ == "__main__":
    if len(sys.argv) != 5:
        print("Использование: python create_db_and_superadmin.py <tg_id> <username> <port> <login>")
        print("Пример: python create_db_and_superadmin.py 123456789 admin_user 8080 admin_login")
        sys.exit(1)
    
    tg_id = int(sys.argv[1])
    username = sys.argv[2]
    port = int(sys.argv[3])
    login = sys.argv[4]
    
    create_db_and_add_superadmin(tg_id, username, port, login)