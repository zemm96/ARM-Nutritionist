# Руководство: Оформление страницы 7 в QStackedWidget (Qt Designer)

## Содержание
1. [Текущая архитектура](#1-текущая-архитектура)
2. [Два подхода к размещению](#2-два-подхода-к-размещению)
3. [Подход A — Promoted Widget (рекомендуется)](#3-подход-a--promoted-widget-рекомендуется)
4. [Подход B — Полный перенос UI в Designer](#4-подход-b--полный-перенос-ui-в-designer)
5. [Навигация и сигналы](#5-навигация-и-сигналы)
6. [Типичные ошибки](#6-типичные-ошибки)

---

## 1. Текущая архитектура

```
QStackedWidget
├── page   (index 0) — Экран входа
├── page_2 (index 1) — Возраст / рост / вес
├── page_3 (index 2) — Уровень активности
├── page_4 (index 3) — Любимые/нелюбимые блюда
├── page_5 (index 4) — Регистрация
├── page_6 (index 5) — Центральный экран
└── page_7 (index 6) — ПУСТО (сюда нужно поместить план питания)
```

Сейчас `MealPlanWidget` создаётся в C++ и добавляется внутрь `page_7`
через `QVBoxLayout` в конструкторе `myqtclass`:

```cpp
m_planWidget = new MealPlanWidget(ui->page_7);
QVBoxLayout *planLayout = new QVBoxLayout(ui->page_7);
planLayout->setContentsMargins(0, 0, 0, 0);
planLayout->addWidget(m_planWidget);
```

Это рабочий вариант, но `page_7` остаётся пустой в `.ui` файле —
Designer её не видит и редактировать через него невозможно.

---

## 2. Два подхода к размещению

| | Подход A: Promoted Widget | Подход B: Всё в Designer |
|---|---|---|
| Логика виджета | Остаётся в `MealPlanWidget` | Переносится в `myqtclass` |
| Редактирование UI | В Designer (геометрия, стили) | Полностью в Designer |
| Сложность | Низкая | Средняя |
| Рекомендуется | ✅ Да | Только если нужен полный контроль в Designer |

---

## 3. Подход A — Promoted Widget (рекомендуется)

Это самый чистый способ: в Designer помещаем «заглушку» `QWidget`,
а Qt в runtime подменяет её на реальный `MealPlanWidget`.

### Шаг 1 — Открыть page_7 в Designer

1. Откройте `myqtclass.ui` в Qt Designer (двойной клик в Qt Creator).
2. В дереве объектов (`Object Inspector`) найдите `page_7`.
3. Кликните по ней — в редакторе откроется пустая страница.

### Шаг 2 — Добавить QWidget-заглушку

1. Из панели **Widget Box** перетащите **Widget** (`QWidget`) на `page_7`.
2. Растяните его на весь размер страницы.
3. Выберите `page_7` → правая кнопка → **Lay Out** → **Lay Out Vertically**.
   Теперь вложенный `QWidget` автоматически занимает всю страницу.
4. Дайте вложенному виджету имя `mealPlanContainer`
   (Properties → `objectName` → `mealPlanContainer`).

### Шаг 3 — Зарегистрировать promoted class

1. Правая кнопка на `mealPlanContainer` → **Promote to…**
2. В открывшемся диалоге:
   - **Base class name**: `QWidget`
   - **Promoted class name**: `MealPlanWidget`
   - **Header file**: `mealplanwidget.h`
3. Нажмите **Add**, затем **Promote**.

Теперь в дереве объектов `mealPlanContainer` отображается как `MealPlanWidget`.
Designer не умеет рендерить кастомные виджеты, поэтому он показывает
пустой прямоугольник — это нормально.

### Шаг 4 — Обновить myqtclass.cpp

Удалите ручное создание виджета — Designer сделает это сам через `setupUi()`:

```cpp
// БЫЛО (убрать):
m_planWidget = new MealPlanWidget(ui->page_7);
QVBoxLayout *planLayout = new QVBoxLayout(ui->page_7);
planLayout->setContentsMargins(0, 0, 0, 0);
planLayout->addWidget(m_planWidget);

// СТАЛО — Designer создал виджет, просто получаем указатель:
m_planWidget = ui->mealPlanContainer;  // тип уже MealPlanWidget*
```

Остальной код (`setUserCalories`, `setParams`, `backRequested`) не меняется.

### Шаг 5 — Обновить myqtclass.h

```cpp
// Было:
MealPlanWidget *m_planWidget = nullptr;

// Стало (тип тот же, просто пометка):
MealPlanWidget *m_planWidget = nullptr;  // = ui->mealPlanContainer после setupUi
```

### Шаг 6 — Пересобрать проект

После изменения `.ui` файла Qt Creator автоматически регенерирует
`ui_myqtclass.h`. Нажмите **Build → Rebuild All**.

---

## 4. Подход B — Полный перенос UI в Designer

Этот подход уместен если вы хотите управлять каждым элементом
страницы 7 напрямую через Designer, без отдельного класса.

### Шаг 1 — Назначить layout для page_7

1. Кликните `page_7` в дереве объектов.
2. Правая кнопка → **Lay Out** → **Lay Out Vertically**.
   Страница получит `QVBoxLayout` и любые добавляемые виджеты
   будут автоматически тянуться на всю высоту.

### Шаг 2 — Добавить элементы интерфейса

Перетащите с панели Widget Box следующие виджеты (сверху вниз):

| Виджет | Object Name | Назначение |
|---|---|---|
| `QLabel` | `planInfoLabel` | Информационная строка (ккал, бюджет) |
| `QPushButton` | `planGenerateBtn` | Кнопка «Сгенерировать» |
| `QLabel` | `planStatusLabel` | Статус / прогресс текстом |
| `QProgressBar` | `planProgressBar` | Анимированный прогресс-бар |
| `QTextEdit` | `planResultEdit` | Поле результата (read-only) |
| `QWidget` | — | Контейнер для нижних кнопок |

Для нижних кнопок:
1. Перетащите `QWidget` в конец вертикального layout.
2. Кликните на него → правая кнопка → **Lay Out Horizontally**.
3. Внутрь добавьте:
   - `QPushButton` с именем `planBackBtn` («← Назад»)
   - `Horizontal Spacer`
   - `QPushButton` с именем `planSaveBtn` («Сохранить»)

### Шаг 3 — Растяжение (stretch)

Чтобы `planResultEdit` занимал максимум места:
1. Кликните на `planResultEdit`.
2. В Properties → `sizePolicy` → **Vertical Policy** → установите `Expanding`.

Или через Layout: правая кнопка на вертикальном layout →
**Add Stretch** после `planProgressBar` и перед нижним рядом кнопок.

### Шаг 4 — Стили

Скопируйте стили из `mealplanwidget.cpp` (`buildUi()`) в поля
`styleSheet` каждого виджета в Designer:

**planGenerateBtn:**
```css
QPushButton {
    background-color: #2D6A30;
    color: #FFFFFF;
    border: none;
    border-radius: 8px;
    padding: 10px 28px;
    font-size: 14px;
    font-weight: 600;
    min-width: 110px;
    min-height: 38px;
}
QPushButton:hover    { background-color: #245727; }
QPushButton:pressed  { background-color: #1A4020; }
QPushButton:disabled { background-color: #B8CFB8; color: #FFFFFF; }
```

**planInfoLabel:**
```css
QLabel { color: #3B6D11; font-size: 12px; }
```

### Шаг 5 — Перенести логику в myqtclass

Поскольку отдельного класса больше нет, всю логику из
`MealPlanWidget` и `mealplanwidget.cpp` переносим в `myqtclass`:

**myqtclass.h** — добавить поля:
```cpp
#include "mealplangenerator.h"
// ...
private:
    MealPlanGenerator *m_generator = nullptr;

    void onPlanProgress(const QString &msg);
    void onPlanReady(const QString &plan);
    void onPlanError(const QString &err);
    void setPlanGenerating(bool busy);
```

**myqtclass.cpp** — конструктор:
```cpp
// Инициализация генератора
const QString sd = QCoreApplication::applicationDirPath();
m_generator = new MealPlanGenerator(this);
m_generator->setGeneratorPath(sd + "/generate_meal_plan.py");
m_generator->setBridgePath   (sd + "/chizhik_bridge.py");
m_generator->setSelectorPath (sd + "/meal_selector.py");
m_generator->setVerifierPath (sd + "/meal_verifier.py");

connect(m_generator, &MealPlanGenerator::progressUpdated,
        this, &myqtclass::onPlanProgress);
connect(m_generator, &MealPlanGenerator::planReady,
        this, &myqtclass::onPlanReady);
connect(m_generator, &MealPlanGenerator::errorOccurred,
        this, &myqtclass::onPlanError);

// Кнопки страницы 7
ui->planProgressBar->setRange(0, 0);
ui->planProgressBar->setVisible(false);
ui->planSaveBtn->setEnabled(false);

connect(ui->planGenerateBtn, &QPushButton::clicked, this, [this]() {
    // ... заполнить MealPlanRequest и вызвать m_generator->generate(req)
});
connect(ui->planBackBtn, &QPushButton::clicked, this, [this]() {
    ui->stackedWidget->setCurrentIndex(5);
});
connect(ui->planSaveBtn, &QPushButton::clicked, this, [this]() {
    QString path = QFileDialog::getSaveFileName(this, "Сохранить план",
        "plan_" + QDateTime::currentDateTime().toString("yyyyMMdd_HHmm") + ".txt",
        "Текстовые файлы (*.txt)");
    if (!path.isEmpty()) {
        QFile f(path);
        if (f.open(QIODevice::WriteOnly | QIODevice::Text))
            QTextStream(&f) << ui->planResultEdit->toPlainText();
    }
});
```

**Слоты:**
```cpp
void myqtclass::onPlanProgress(const QString &msg) {
    ui->planStatusLabel->setText(msg);
}
void myqtclass::onPlanReady(const QString &plan) {
    setPlanGenerating(false);
    ui->planStatusLabel->setText("План готов!");
    ui->planResultEdit->setPlainText(plan);
    ui->planSaveBtn->setEnabled(true);
}
void myqtclass::onPlanError(const QString &err) {
    setPlanGenerating(false);
    ui->planStatusLabel->clear();
    QMessageBox::critical(this, "Ошибка генерации", err);
}
void myqtclass::setPlanGenerating(bool busy) {
    ui->planGenerateBtn->setEnabled(!busy);
    ui->planProgressBar->setVisible(busy);
    if (!busy) ui->planStatusLabel->clear();
}
```

После этого классы `MealPlanWidget` / `mealplanwidget.cpp` /
`mealplanwidget.h` можно удалить из проекта.

---

## 5. Навигация и сигналы

В обоих подходах навигация одинакова:

```cpp
// Переход НА страницу 7 (из on_mealPlanBtn_clicked):
ui->stackedWidget->setCurrentIndex(6);

// Переход ОБРАТНО на центральный экран:
ui->stackedWidget->setCurrentIndex(5);
```

---

## 6. Типичные ошибки

### «promoted widget not found» при сборке
Убедитесь, что в `.pro` файле подключены `mealplanwidget.h` и
`mealplanwidget.cpp`:
```qmake
HEADERS += mealplanwidget.h
SOURCES += mealplanwidget.cpp
```

### page_7 не реагирует на Lay Out в Designer
Если страница слишком маленькая, Designer иногда игнорирует команду.
Решение: временно увеличьте окно (`geometry` → `width/height`),
примените layout, верните размер обратно.

### QProgressBar не анимируется
Для бесконечной анимации нужны `setRange(0, 0)` + `setVisible(true)`.
Если поставить `setRange(0, 100)`, он будет стоять на 0 без вызова
`setValue`.

### Promoted widget отображается как пустой прямоугольник в Designer
Это нормально — Designer не запускает код кастомного виджета.
В runtime всё отображается корректно.

### После Rebuild All ошибки в ui_myqtclass.h
Если Designer создал имя, совпадающее с полем в `myqtclass.h`
(например, оба называются `m_planWidget`), будет конфликт.
Переименуйте одно из них.
