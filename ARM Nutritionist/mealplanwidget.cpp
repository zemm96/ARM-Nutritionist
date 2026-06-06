#include "mealplanwidget.h"
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QFileDialog>
#include <QMessageBox>
#include <QDateTime>
#include <QFile>
#include <QCoreApplication>
#include <QTextStream>
#include <QFont>
// Возвращает папку с Python-скриптами помощниками.
// ARM Nutritionist.pro копирует их рядом с exe при каждой сборке,
// поэтому applicationDirPath() всегда верный путь.
static QString resolveScriptsDir()
{
    return QCoreApplication::applicationDirPath();
}
MealPlanWidget::MealPlanWidget(QWidget *parent)
    : QWidget(parent)
    , m_generator(new MealPlanGenerator(this))
{
    // Настраиваем пути к скриптам: работает и в shadow-сборке (скрипты в дереве исходников),
    // и в задеплоенной сборке (скрипты скопированы рядом с exe).
    const QString sd = resolveScriptsDir();
    m_generator->setGeneratorPath(sd + "/generate_meal_plan.py");
    m_generator->setBridgePath   (sd + "/chizhik_bridge.py");
    m_generator->setSelectorPath (sd + "/meal_selector.py");
    m_generator->setVerifierPath (sd + "/meal_verifier.py");

    buildUi();

    connect(m_generator, &MealPlanGenerator::progressUpdated,
            this, &MealPlanWidget::onProgress);
    connect(m_generator, &MealPlanGenerator::planReady,
            this, &MealPlanWidget::onPlanReady);
    connect(m_generator, &MealPlanGenerator::errorOccurred,
            this, &MealPlanWidget::onError);
}
void MealPlanWidget::setUserCalories(double totalCalories,
                                      double proteinPct,
                                      double fatPct,
                                      double carbPct)
{
    m_totalCalories = totalCalories;
    m_proteinPct    = proteinPct;
    m_fatPct        = fatPct;
    m_carbPct       = carbPct;
}

void MealPlanWidget::setParams(double weeklyBudget,
                                int    varietyLevel,
                                const QString &likedFoods,
                                const QString &dislikedFoods)
{
    m_weeklyBudget  = weeklyBudget;
    m_varietyLevel  = varietyLevel;
    m_likedFoods    = likedFoods;
    m_dislikedFoods = dislikedFoods;

    // Обновляем информационную метку
    QString varietyStr;
    switch (varietyLevel) {
    case 1: varietyStr = "Низкий"; break;
    case 3: varietyStr = "Высокий"; break;
    default: varietyStr = "Средний";
    }
    QString info = QString("%1 ккал/день  |  %2 ₽/нед  |  Разнообразие: %3")
                       .arg(qRound(m_totalCalories))
                       .arg(weeklyBudget, 0, 'f', 0)
                       .arg(varietyStr);

    if (!likedFoods.isEmpty())
        info += "  |  Любимые: " + likedFoods.left(30) + (likedFoods.size() > 30 ? "…" : "");
    if (!dislikedFoods.isEmpty())
        info += "  |  Нелюбимые: " + dislikedFoods.left(30) + (dislikedFoods.size() > 30 ? "…" : "");

    if (m_infoLabel)
        m_infoLabel->setText(info);
}

void MealPlanWidget::buildUi()
{
    QVBoxLayout *root = new QVBoxLayout(this);
    root->setContentsMargins(16, 12, 16, 12);
    root->setSpacing(10);

    // ── Информационная строка ─────────────────────────────────────────────────
    m_infoLabel = new QLabel(this);
    m_infoLabel->setWordWrap(true);
    m_infoLabel->setStyleSheet("color:#3B6D11; font-size:12px;");
    root->addWidget(m_infoLabel);

    // ── Кнопка генерации ─────────────────────────────────────────────────────
    m_generateBtn = new QPushButton("Сгенерировать план питания", this);
    m_generateBtn->setMinimumHeight(42);
    QFont bf = m_generateBtn->font();
    bf.setPointSize(12); bf.setBold(true);
    m_generateBtn->setFont(bf);
    m_generateBtn->setStyleSheet(
        "QPushButton { background-color:#2D6A30; color:#FFFFFF; border:none; border-radius:8px; padding:10px 28px; font-size:14px; font-weight:600; min-width:110px; min-height:38px; }"
        "QPushButton:hover { background-color:#245727; }"
        "QPushButton:pressed { background-color:#1A4020; }"
        "QPushButton:disabled { background-color:#B8CFB8; color:#FFFFFF; }");
    connect(m_generateBtn, &QPushButton::clicked,
            this, &MealPlanWidget::onGenerateClicked);
    root->addWidget(m_generateBtn);

    // ── Статус / прогресс ────────────────────────────────────────────────────
    m_statusLabel = new QLabel(this);
    m_statusLabel->setWordWrap(true);
    root->addWidget(m_statusLabel);

    m_progressBar = new QProgressBar(this);
    m_progressBar->setRange(0, 0);
    m_progressBar->setVisible(false);
    root->addWidget(m_progressBar);
    // ── Результат ────────────────────────────────────────────────────────────
    m_resultEdit = new QTextEdit(this);
    m_resultEdit->setReadOnly(true);
    m_resultEdit->setPlaceholderText("Здесь появится сгенерированный план питания...");
    m_resultEdit->setMinimumHeight(280);
    root->addWidget(m_resultEdit, 1);
    // ── Нижние кнопки ────────────────────────────────────────────────────────
    QHBoxLayout *btnRow = new QHBoxLayout();
    m_backBtn = new QPushButton("Назад", this);
    m_backBtn->setMinimumHeight(34);
    connect(m_backBtn, &QPushButton::clicked,
            this, &MealPlanWidget::backRequested);
    btnRow->addWidget(m_backBtn);
    btnRow->addStretch();
    m_saveBtn = new QPushButton("Сохранить", this);
    m_saveBtn->setMinimumHeight(34);
    m_saveBtn->setEnabled(false);
    connect(m_saveBtn, &QPushButton::clicked, this, [this]() {
        QString path = QFileDialog::getSaveFileName(
            this, "Сохранить план питания",
            "plan_" + QDateTime::currentDateTime().toString("yyyyMMdd_HHmm") + ".txt",
            "Текстовые файлы (*.txt);;Все файлы (*)");
        if (path.isEmpty()) return;
        QFile f(path);
        if (f.open(QIODevice::WriteOnly | QIODevice::Text))
            QTextStream(&f) << m_resultEdit->toPlainText();
    });
    btnRow->addWidget(m_saveBtn);

    root->addLayout(btnRow);
}
void MealPlanWidget::onGenerateClicked()
{
    MealPlanRequest req;
    req.totalCalories  = m_totalCalories;
    req.proteinPercent = m_proteinPct;
    req.fatPercent     = m_fatPct;
    req.carbPercent    = m_carbPct;
    req.weeklyBudget   = m_weeklyBudget;
    req.varietyLevel   = m_varietyLevel;
    req.likedFoods     = m_likedFoods;
    req.dislikedFoods  = m_dislikedFoods;
    m_resultEdit->clear();
    m_saveBtn->setEnabled(false);
    setGenerating(true);
    m_generator->generate(req);
}
void MealPlanWidget::onProgress(const QString &msg)
{
    m_statusLabel->setText(msg);
}
void MealPlanWidget::onPlanReady(const QString &plan)
{
    setGenerating(false);
    m_statusLabel->setText("План готов!");
    m_resultEdit->setPlainText(plan);
    m_saveBtn->setEnabled(true);
}
void MealPlanWidget::onError(const QString &err)
{
    setGenerating(false);
    m_statusLabel->clear();
    QMessageBox::critical(this, "Ошибка генерации", err);
}
void MealPlanWidget::setGenerating(bool busy)
{
    m_generateBtn->setEnabled(!busy);
    m_progressBar->setVisible(busy);
    if (!busy) m_statusLabel->clear();
}
