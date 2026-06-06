#ifndef MEALPLANWIDGET_H
#define MEALPLANWIDGET_H

#include <QWidget>
#include <QLabel>
#include <QTextEdit>
#include <QPushButton>
#include <QProgressBar>
#include "mealplangenerator.h"

// ─────────────────────────────────────────────────────────────────────────────
// Экран результата генерации плана питания.
// Все параметры (бюджет, разнообразие, любимые/нелюбимые) задаются
// на центральном экране (index 5 в stackedWidget) и передаются сюда через
// setUserCalories() + setParams() перед показом виджета.
// ─────────────────────────────────────────────────────────────────────────────
class MealPlanWidget : public QWidget
{
    Q_OBJECT
public:
    explicit MealPlanWidget(QWidget *parent = nullptr);

    // Вызывается из UserProfileSetup перед переходом на этот экран
    void setUserCalories(double totalCalories,
                         double proteinPct,
                         double fatPct,
                         double carbPct);

    void setParams(double weeklyBudget,
                   int    varietyLevel,       // 1=Низкий 2=Средний 3=Высокий
                   const QString &likedFoods,
                   const QString &dislikedFoods);

    void setPythonPath(const QString &p) { m_generator->setPythonPath(p); }
    void setBridgePath(const QString &p) { m_generator->setBridgePath(p); }

signals:
    void backRequested();

private slots:
    void onGenerateClicked();
    void onProgress(const QString &msg);
    void onPlanReady(const QString &plan);
    void onError(const QString &err);

private:
    void buildUi();
    void setGenerating(bool busy);

    // UI
    QLabel       *m_infoLabel    = nullptr;   // краткая сводка параметров
    QLabel       *m_statusLabel  = nullptr;
    QProgressBar *m_progressBar  = nullptr;
    QPushButton  *m_generateBtn  = nullptr;
    QPushButton  *m_backBtn      = nullptr;
    QPushButton  *m_saveBtn      = nullptr;
    QTextEdit    *m_resultEdit   = nullptr;

    // Данные
    MealPlanGenerator *m_generator    = nullptr;
    double  m_totalCalories  = 2000;
    double  m_proteinPct     = 25;
    double  m_fatPct         = 30;
    double  m_carbPct        = 45;
    double  m_weeklyBudget   = 2000;
    int     m_varietyLevel   = 2;
    QString m_likedFoods;
    QString m_dislikedFoods;
};

#endif // MEALPLANWIDGET_H
