#include "mealplangenerator.h"

#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonArray>
#include <QJsonValue>
#include <QCoreApplication>
#include <QFile>
#include <QFileInfo>
#include <QDateTime>
#include <QDebug>
#include <QProcessEnvironment>

MealPlanGenerator::MealPlanGenerator(QObject *parent)
    : QObject(parent)
    , m_watchdog(new QTimer(this))
{
    m_watchdog->setSingleShot(true);
    connect(m_watchdog, &QTimer::timeout, this, [this]() {
        if (m_process) {
            m_process->disconnect();
            m_process->kill();
            m_process->deleteLater();
            m_process = nullptr;
        }
        emit errorOccurred(
            "Модель не успела сгенерировать план за отведённое время.\n"
            "Попробуйте ещё раз: при первом запуске модель загружается дольше.");
    });
}


void MealPlanGenerator::generate(const MealPlanRequest &req)
{
    m_req             = req;
    m_compactProducts = QJsonArray();

    const QString dir         = QCoreApplication::applicationDirPath();
    m_productsJsonPath        = dir + "/arm_products.json";
    m_compactProductsJsonPath = dir + "/arm_compact.json";
    m_planJsonPath            = dir + "/arm_plan.json";

    static constexpr int kCacheMaxSecs = 4 * 60 * 60;
    QFileInfo cacheInfo(m_productsJsonPath);
    if (cacheInfo.exists() &&
        cacheInfo.lastModified().secsTo(QDateTime::currentDateTime()) < kCacheMaxSecs)
    {
        QFile f(m_productsJsonPath);
        if (f.open(QIODevice::ReadOnly)) {
            QByteArray cached = f.readAll();
            QJsonDocument doc = QJsonDocument::fromJson(cached);
            if (doc.isArray() && !doc.array().isEmpty()) {
                if (!m_req.likedFoods.trimmed().isEmpty()) {
                    emit progressUpdated("Ищем любимые продукты в каталоге...");
                    runLikedFoodsSearch();
                } else {
                    emit progressUpdated("Отбираем подходящие товары...");
                    runSelector();
                }
                return;
            }
        }
    }

    emit progressUpdated("Загружаем ассортимент Чижика...");
    runParser();
}

//Вспомогательный метод: создаёт QProcess и запускает python
QProcess *MealPlanGenerator::launchProcess(
    const QStringList &args,
    void (MealPlanGenerator::*slot)(int, QProcess::ExitStatus))
{
    if (m_process) {
        m_process->disconnect();
        m_process->kill();
        m_process->deleteLater();
        m_process = nullptr;
    }
    m_procOut.clear();

    m_process = new QProcess(this);
    m_process->setWorkingDirectory(QCoreApplication::applicationDirPath());

    QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
    env.insert("PYTHONIOENCODING", "utf-8");
    env.insert("PYTHONUTF8", "1");
    m_process->setProcessEnvironment(env);

    connect(m_process, &QProcess::readyReadStandardOutput, this, [this]() {
        m_procOut += m_process->readAllStandardOutput();
    });
    connect(m_process,
            QOverload<int, QProcess::ExitStatus>::of(&QProcess::finished),
            this, slot);

    m_process->start(m_pythonPath, args);

    if (!m_process->waitForStarted(3000)) {
        emit errorOccurred("Не удалось запустить Python.\nПроверьте путь: " + m_pythonPath);
        return nullptr;
    }

    m_watchdog->start(90 * 1000);
    return m_process;
}


void MealPlanGenerator::runLikedFoodsSearch()
{
    QStringList args;
    args << m_bridgePath
         << m_req.likedFoods                              // query = любимые продукты
         << QString::number(m_req.weeklyBudget, 'f', 2)
         << "25"
         << ""                                            // output_json не нужен
         << QString::number(m_req.varietyLevel)
         << m_req.likedFoods;

    if (launchProcess(args, &MealPlanGenerator::onLikedFoodsSearchFinished))
        m_watchdog->start(5 * 60 * 1000); // веб-скрапинг может занять до 5 минут
}

void MealPlanGenerator::onLikedFoodsSearchFinished(int exitCode, QProcess::ExitStatus)
{
    m_watchdog->stop();
    m_procOut += m_process->readAllStandardOutput();

    // При ошибке поиска просто используем существующий кэш
    QJsonDocument newDoc = QJsonDocument::fromJson(m_procOut);
    if (exitCode != 0 || !newDoc.isArray()) {
        emit progressUpdated("Отбираем подходящие товары...");
        runSelector();
        return;
    }

    // Загружаем существующий кэш
    QJsonArray existing;
    {
        QFile f(m_productsJsonPath);
        if (f.open(QIODevice::ReadOnly))
            existing = QJsonDocument::fromJson(f.readAll()).array();
    }

    // Мёржим: добавляем только те продукты, которых ещё нет в кэше
    QSet<QString> existingTitles;
    for (const QJsonValue &v : existing)
        existingTitles.insert(v.toObject()["title"].toString().toLower());

    QJsonArray merged = existing;
    int added = 0;
    for (const QJsonValue &v : newDoc.array()) {
        const QString title = v.toObject()["title"].toString().toLower();
        if (!title.isEmpty() && !existingTitles.contains(title)) {
            merged.append(v);
            existingTitles.insert(title);
            ++added;
        }
    }

    if (added > 0) {
        QFile wf(m_productsJsonPath);
        if (wf.open(QIODevice::WriteOnly | QIODevice::Truncate))
            wf.write(QJsonDocument(merged).toJson(QJsonDocument::Compact));
        emit progressUpdated(
            QString("Найдено %1 новых любимых продуктов. Отбираем...").arg(added));
    } else {
        emit progressUpdated("Отбираем подходящие товары...");
    }

    runSelector();
}

void MealPlanGenerator::runParser()
{
    QStringList args;
    args << m_bridgePath
         << ""
         << QString::number(m_req.weeklyBudget, 'f', 2)
         << "25"
         << m_productsJsonPath
         << QString::number(m_req.varietyLevel)
         << m_req.likedFoods;

    if (launchProcess(args, &MealPlanGenerator::onParserFinished))
        m_watchdog->start(5 * 60 * 1000); // веб-скрапинг может занять до 5 минут
}

void MealPlanGenerator::onParserFinished(int exitCode, QProcess::ExitStatus)
{
    m_watchdog->stop();
    m_procOut += m_process->readAllStandardOutput();
    const QByteArray err = m_process->readAllStandardError();

    if (exitCode != 0) {
        QString detail = QString::fromUtf8(m_procOut.isEmpty() ? err : m_procOut).trimmed();
        if (detail.isEmpty())
            detail = "Парсер завершился без сообщения об ошибке.";
        emit errorOccurred("Парсер Чижика завершился с ошибкой:\n" + detail);
        return;
    }

    const QByteArray toSave = m_procOut.isEmpty() ? QByteArray("[]") : m_procOut;
    {
        QFile f(m_productsJsonPath);
        if (f.open(QIODevice::WriteOnly | QIODevice::Truncate))
            f.write(toSave);
    }

    QJsonDocument doc = QJsonDocument::fromJson(toSave);
    if (doc.isObject() && doc.object().contains("error")) {
        emit errorOccurred("Парсер: " + doc.object()["error"].toString());
        return;
    }
    if (!doc.isArray() || doc.array().isEmpty()) {
        emit errorOccurred("Парсер не нашёл ни одного товара.\n"
                           "Проверьте интернет-соединение и повторите попытку.");
        return;
    }

    emit progressUpdated(
        QString("Получено %1 товаров. Отбираем подходящие...")
        .arg(doc.array().size()));
    runSelector();
}

void MealPlanGenerator::runSelector()
{
    QStringList args;
    args << m_selectorPath
         << m_productsJsonPath
         << QString::number(m_req.weeklyBudget,   'f', 2)
         << QString::number(m_req.totalCalories,  'f', 1)
         << QString::number(m_req.proteinPercent, 'f', 1)
         << QString::number(m_req.fatPercent,     'f', 1)
         << QString::number(m_req.carbPercent,    'f', 1)
         << QString::number(m_req.varietyLevel)
         << m_req.dislikedFoods
         << m_req.likedFoods;

    launchProcess(args, &MealPlanGenerator::onSelectorFinished);
}

void MealPlanGenerator::onSelectorFinished(int exitCode, QProcess::ExitStatus)
{
    m_watchdog->stop();
    m_procOut += m_process->readAllStandardOutput();
    const QByteArray err = m_process->readAllStandardError();

    if (exitCode != 0) {
        emit errorOccurred("Селектор завершился с ошибкой:\n" +
                           QString::fromUtf8(err.isEmpty() ? m_procOut : err));
        return;
    }

    QJsonDocument doc = QJsonDocument::fromJson(m_procOut);
    if (doc.isObject() && doc.object().contains("error")) {
        emit errorOccurred("Селектор: " + doc.object()["error"].toString());
        return;
    }
    if (!doc.isArray() || doc.array().isEmpty()) {
        const QString detail = QString::fromUtf8(m_procOut).trimmed();
        emit errorOccurred("Селектор не вернул продуктов.\n" +
                           (detail.isEmpty()
                                ? QString("Попробуйте увеличить бюджет.")
                                : QString("Вывод селектора: ") + detail));
        return;
    }

    m_compactProducts = doc.array();
    {
        QFile cf(m_compactProductsJsonPath);
        if (cf.open(QIODevice::WriteOnly | QIODevice::Truncate))
            cf.write(QJsonDocument(m_compactProducts).toJson(QJsonDocument::Compact));
    }

    emit progressUpdated(
        QString("Отобрано %1 продуктов. Составляем меню...")
        .arg(m_compactProducts.size()));
    runGenerator();
}


void MealPlanGenerator::runGenerator()
{
    QStringList args;
    args << m_generatorPath
         << "--products" << m_compactProductsJsonPath
         << "--output"   << m_planJsonPath
         << "--calories" << QString::number(m_req.totalCalories,  'f', 1)
         << "--protein"  << QString::number(m_req.proteinPercent, 'f', 1)
         << "--fat"      << QString::number(m_req.fatPercent,     'f', 1)
         << "--carbs"    << QString::number(m_req.carbPercent,    'f', 1)
         << "--budget"   << QString::number(m_req.weeklyBudget,   'f', 2)
         << "--variety"  << QString::number(m_req.varietyLevel);

    if (!m_req.likedFoods.trimmed().isEmpty())
        args << "--liked" << m_req.likedFoods;
    if (!m_req.dislikedFoods.trimmed().isEmpty())
        args << "--disliked" << m_req.dislikedFoods;

    if (!launchProcess(args, &MealPlanGenerator::onGeneratorFinished))
        return;

    emit progressUpdated("Генерируем план питания, это может занять несколько минут...");
    m_watchdog->start(90 * 60 * 1000);
}

void MealPlanGenerator::onGeneratorFinished(int exitCode, QProcess::ExitStatus)
{
    m_watchdog->stop();
    const QByteArray err = m_process->readAllStandardError();

    if (exitCode != 0) {
        const QString detail = QString::fromUtf8(
            m_procOut.isEmpty() ? err : m_procOut).trimmed();
        emit errorOccurred("Генератор завершился с ошибкой:\n" +
                           (detail.isEmpty() ? QString("Нет деталей.") : detail));
        return;
    }

    if (!QFileInfo::exists(m_planJsonPath)) {
        emit errorOccurred("Генератор не создал файл плана:\n" + m_planJsonPath);
        return;
    }

    emit progressUpdated("Проверяем план и считаем КБЖУ...");
    runVerifier();
}
// Стадия 4 — верификация, расчёт КБЖУ, форматирование
void MealPlanGenerator::runVerifier()
{
    QStringList args;
    args << m_verifierPath
         << m_planJsonPath
         << m_compactProductsJsonPath
         << QString::number(m_req.totalCalories,  'f', 1)
         << QString::number(m_req.proteinPercent, 'f', 1)
         << QString::number(m_req.fatPercent,     'f', 1)
         << QString::number(m_req.carbPercent,    'f', 1)
         << QString::number(m_req.weeklyBudget,   'f', 2)
         << QString::number(m_req.varietyLevel)
         << m_req.likedFoods
         << m_req.dislikedFoods;

    launchProcess(args, &MealPlanGenerator::onVerifierFinished);
}

void MealPlanGenerator::onVerifierFinished(int exitCode, QProcess::ExitStatus)
{
    m_watchdog->stop();
    m_procOut += m_process->readAllStandardOutput();

    if (exitCode != 0) {
        const QByteArray err = m_process->readAllStandardError();
        emit errorOccurred("Верификатор завершился с ошибкой:\n" +
                           QString::fromUtf8(err.isEmpty() ? m_procOut : err));
        return;
    }

    QString result = QString::fromUtf8(m_procOut).trimmed();
    if (result.isEmpty()) {
        emit errorOccurred("Верификатор не вернул данных.");
        return;
    }

    emit planReady(result);
}
