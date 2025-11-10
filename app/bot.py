import asyncio
import logging
import os
from typing import Dict, List, Optional
from enum import Enum
from dotenv import load_dotenv

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# Состояния бота
class BotState(Enum):
    MAIN_MENU = "main_menu"
    SEARCHING = "searching"
    DOWNLOADING = "downloading"
    PLAYER_CONTROL = "player_control"


# Модели данных
class Movie:
    def __init__(self, title: str, year: str, quality: str, size: str, download_url: str = ""):
        self.title = title
        self.year = year
        self.quality = quality
        self.size = size
        self.download_url = download_url


class DownloadTask:
    def __init__(self, movie: Movie, task_id: str):
        self.movie = movie
        self.task_id = task_id
        self.status = "В очереди"
        self.progress = 0
        self.downloaded_bytes = 0
        self.total_bytes = 0


class MovieBot:
    def __init__(self):
        self.user_states: Dict[int, BotState] = {}
        self.download_tasks: Dict[str, DownloadTask] = {}
        self.downloaded_movies: List[Movie] = []
        self.task_counter = 0

    def get_user_state(self, user_id: int) -> BotState:
        return self.user_states.get(user_id, BotState.MAIN_MENU)

    def set_user_state(self, user_id: int, state: BotState):
        self.user_states[user_id] = state

    async def search_movies(self, query: str) -> List[Movie]:
        # Заглушка для поиска фильмов
        await asyncio.sleep(1)  # Имитация задержки сети

        mock_movies = [
            Movie("Интерстеллар", "2014", "1080p", "2.1 GB"),
            Movie("Интерстеллар", "2014", "720p", "1.4 GB"),
            Movie("Интерстеллар 4K", "2014", "2160p", "8.5 GB"),
            Movie("Начало", "2010", "1080p", "1.9 GB"),
            Movie("Начало", "2010", "720p", "1.2 GB"),
            Movie("Матрица", "1999", "1080p", "2.3 GB"),
            Movie("Матрица", "1999", "720p", "1.5 GB"),
            Movie("Крепкий орешек", "1988", "1080p", "1.8 GB"),
        ]

        # Фильтрация по запросу - исправленная логика
        query_lower = query.lower().strip()
        filtered_movies = []

        for movie in mock_movies:
            # Ищем частичное совпадение в названии
            if query_lower in movie.title.lower():
                filtered_movies.append(movie)

        return filtered_movies

    async def start_download(self, movie: Movie) -> str:
        # Создание задачи загрузки
        self.task_counter += 1
        task_id = f"task_{self.task_counter}"

        download_task = DownloadTask(movie, task_id)
        self.download_tasks[task_id] = download_task

        # Запуск фоновой задачи загрузки
        asyncio.create_task(self._simulate_download(download_task))

        return task_id

    async def _simulate_download(self, download_task: DownloadTask):
        # Имитация процесса загрузки
        download_task.status = "Загружается"

        # Имитация прогресса загрузки
        for progress in range(0, 101, 10):
            await asyncio.sleep(2)
            download_task.progress = progress
            download_task.status = f"Загружается ({progress}%)"

        download_task.status = "Завершено"

        # Добавляем в список загруженных фильмов
        self.downloaded_movies.append(download_task.movie)

    async def get_download_status(self) -> List[DownloadTask]:
        return list(self.download_tasks.values())

    async def control_player(self, action: str) -> str:
        # Заглушка управления плеером
        actions = {
            "tv_on": "Телевизор включен",
            "tv_off": "Телевизор выключен",
            "play": "Воспроизведение начато",
            "pause": "Воспроизведение приостановлено",
            "stop": "Воспроизведение остановлено"
        }
        return actions.get(action, "Команда не распознана")


# Создаем экземпляр бота
movie_bot = MovieBot()


# Клавиатуры
def get_main_keyboard():
    keyboard = [
        [KeyboardButton("🔍 Поиск фильма")],
        [KeyboardButton("📥 Статус загрузок"), KeyboardButton("🎬 Загруженные фильмы")],
        [KeyboardButton("📺 Управление плеером")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_movies_keyboard(movies: List[Movie], page: int = 0, search_query: str = ""):
    keyboard = []
    items_per_page = 5

    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    paginated_movies = movies[start_idx:end_idx]

    for i, movie in enumerate(paginated_movies):
        actual_index = start_idx + i
        button_text = f"{movie.title} ({movie.year}) - {movie.quality} - {movie.size}"
        callback_data = f"download_{actual_index}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])

    # Кнопки навигации
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"page_{page - 1}"))
    if end_idx < len(movies):
        nav_buttons.append(InlineKeyboardButton("Вперед ➡️", callback_data=f"page_{page + 1}"))

    if nav_buttons:
        keyboard.append(nav_buttons)

    keyboard.append([InlineKeyboardButton("↩️ Назад в меню", callback_data="back_to_menu")])

    # Сохраняем поисковый запрос для пагинации
    if search_query:
        for button_row in keyboard:
            for button in button_row:
                if hasattr(button, 'callback_data') and button.callback_data:
                    button.callback_data += f"_{search_query}"

    return InlineKeyboardMarkup(keyboard)


def get_player_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("Включить ТВ", callback_data="player_tv_on"),
            InlineKeyboardButton("Выключить ТВ", callback_data="player_tv_off")
        ],
        [
            InlineKeyboardButton("Воспроизвести", callback_data="player_play"),
            InlineKeyboardButton("Пауза", callback_data="player_pause"),
            InlineKeyboardButton("Стоп", callback_data="player_stop")
        ],
        [InlineKeyboardButton("↩️ Назад в меню", callback_data="back_to_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_back_keyboard():
    keyboard = [[InlineKeyboardButton("↩️ Назад в меню", callback_data="back_to_menu")]]
    return InlineKeyboardMarkup(keyboard)


def get_search_back_keyboard():
    keyboard = [
        [InlineKeyboardButton("🔍 Новый поиск", callback_data="new_search")],
        [InlineKeyboardButton("↩️ Назад в меню", callback_data="back_to_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


# Обработчики команд
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    movie_bot.set_user_state(user_id, BotState.MAIN_MENU)

    welcome_text = (
        "Добро пожаловать в MovieBot!\n\n"
        "Доступные функции:\n"
        "• Поиск и загрузка фильмов\n"
        "• Просмотр статуса загрузок\n"
        "• Управление медиаплеером\n\n"
        "Выберите действие:"
    )

    await update.message.reply_text(
        welcome_text,
        reply_markup=get_main_keyboard()
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    current_state = movie_bot.get_user_state(user_id)
    message_text = update.message.text

    if current_state == BotState.SEARCHING:
        await handle_search(update, context, message_text)
    else:
        if message_text == "🔍 Поиск фильма":
            movie_bot.set_user_state(user_id, BotState.SEARCHING)
            await update.message.reply_text(
                "Введите название фильма для поиска:",
                reply_markup=get_back_keyboard()
            )
        elif message_text == "📥 Статус загрузок":
            await show_download_status(update, context)
        elif message_text == "🎬 Загруженные фильмы":
            await show_downloaded_movies(update, context)
        elif message_text == "📺 Управление плеером":
            await show_player_control(update, context)
        else:
            await update.message.reply_text(
                "Пожалуйста, используйте кнопки для навигации",
                reply_markup=get_main_keyboard()
            )


async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str):
    user_id = update.effective_user.id

    if not query.strip():
        await update.message.reply_text("Пожалуйста, введите название фильма:")
        return

    await update.message.reply_text(f"🔍 Ищем фильмы по запросу: '{query}'...")

    movies = await movie_bot.search_movies(query)

    if not movies:
        await update.message.reply_text(
            f"По запросу '{query}' фильмы не найдены. Попробуйте другой запрос.",
            reply_markup=get_search_back_keyboard()
        )
        return

    context.user_data['search_results'] = movies
    context.user_data['current_page'] = 0
    context.user_data['search_query'] = query

    await update.message.reply_text(
        f"По запросу '{query}' найдено фильмов: {len(movies)}\nВыберите вариант для загрузки:",
        reply_markup=get_movies_keyboard(movies, 0, query)
    )


async def show_download_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = await movie_bot.get_download_status()

    if not tasks:
        await update.message.reply_text(
            "Нет активных загрузок",
            reply_markup=get_main_keyboard()
        )
        return

    status_text = "📊 Статус загрузок:\n\n"
    for task in tasks:
        status_text += (
            f"🎬 {task.movie.title}\n"
            f"📁 Качество: {task.movie.quality}\n"
            f"📦 Размер: {task.movie.size}\n"
            f"🔄 Статус: {task.status}\n"
            f"📈 Прогресс: {task.progress}%\n"
            f"{'-' * 30}\n"
        )

    await update.message.reply_text(
        status_text,
        reply_markup=get_main_keyboard()
    )


async def show_downloaded_movies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    movies = movie_bot.downloaded_movies

    if not movies:
        await update.message.reply_text(
            "Нет загруженных фильмов",
            reply_markup=get_main_keyboard()
        )
        return

    movies_text = "🎬 Загруженные фильмы:\n\n"
    for i, movie in enumerate(movies, 1):
        movies_text += f"{i}. {movie.title} ({movie.year}) - {movie.quality}\n"

    await update.message.reply_text(
        movies_text,
        reply_markup=get_main_keyboard()
    )


async def show_player_control(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📺 Управление медиаплеером:",
        reply_markup=get_player_keyboard()
    )


# Обработчик callback-запросов
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = query.from_user.id

    if data == "back_to_menu":
        movie_bot.set_user_state(user_id, BotState.MAIN_MENU)
        await query.edit_message_text(
            "Главное меню:",
            reply_markup=get_main_keyboard()
        )

    elif data == "new_search":
        movie_bot.set_user_state(user_id, BotState.SEARCHING)
        await query.edit_message_text(
            "Введите название фильма для поиска:",
            reply_markup=get_back_keyboard()
        )

    elif data.startswith("page_"):
        parts = data.split("_")
        page = int(parts[1])
        movies = context.user_data.get('search_results', [])
        search_query = context.user_data.get('search_query', "")

        context.user_data['current_page'] = page

        await query.edit_message_text(
            f"По запросу '{search_query}' найдено фильмов: {len(movies)}\nВыберите вариант для загрузки:",
            reply_markup=get_movies_keyboard(movies, page, search_query)
        )

    elif data.startswith("download_"):
        parts = data.split("_")
        movie_index = int(parts[1])
        movies = context.user_data.get('search_results', [])

        if 0 <= movie_index < len(movies):
            selected_movie = movies[movie_index]
            task_id = await movie_bot.start_download(selected_movie)

            await query.edit_message_text(
                f"✅ Загрузка начата:\n"
                f"🎬 {selected_movie.title}\n"
                f"📁 {selected_movie.quality} - {selected_movie.size}\n"
                f"🆔 ID задачи: {task_id}\n\n"
                f"Статус можно проверить в разделе 'Статус загрузок'",
                reply_markup=get_back_keyboard()
            )

    elif data.startswith("player_"):
        action = data.split("_")[1]
        result = await movie_bot.control_player(action)
        await query.edit_message_text(
            f"📺 {result}",
            reply_markup=get_player_keyboard()
        )


def run_bot():
    TOKEN = os.getenv('BOT_TOKEN')

    if not TOKEN:
        logger.error("Токен бота не найден! Убедитесь, что файл .env существует и содержит BOT_TOKEN")
        return

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("Бот запущен...")
    application.run_polling()