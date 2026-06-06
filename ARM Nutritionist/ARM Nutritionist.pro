QT       += core gui widgets sql network

HEADERS += \
    mealplangenerator.h \
    mealplanwidget.h
SOURCES += \
    mealplangenerator.cpp \
    mealplanwidget.cpp
greaterThan(QT_MAJOR_VERSION, 4): QT += widgets


CONFIG += c++17

SOURCES += \
    CalorieCalculator.cpp \
    DatabaseManager.cpp \
    main.cpp \
    userprofilesetup.cpp

HEADERS += \
    CalorieCalculator.h \
    DatabaseManager.h \
    userprofilesetup.h

FORMS += \
    userprofilesetup.ui

# Правила развёртывания по умолчанию
qnx: target.path = /tmp/$${TARGET}/bin
else: unix:!android: target.path = /opt/$${TARGET}/bin
!isEmpty(target.path): INSTALLS += target

DISTFILES += \
    style.qss

# ── Копирование Python-скриптов рядом с .exe после каждой сборки ─────────────
win32 {
    CONFIG(debug, debug|release): PY_OUT = $$shell_path($$OUT_PWD/debug)
    else:                          PY_OUT = $$shell_path($$OUT_PWD/release)

    PY_FILES = \
        generate_meal_plan.py \
        chizhik_bridge.py \
        chi901.py \
        meal_selector.py \
        meal_verifier.py

    for(f, PY_FILES) {
        QMAKE_POST_LINK += $$QMAKE_COPY $$shell_path($$PWD/$$f) $$PY_OUT &
    }
}
