#ifndef MEALPLANGENERATOR_H
#define MEALPLANGENERATOR_H

#include <QObject>
#include <QString>
#include <QStringList>
#include <QJsonArray>
#include <QProcess>
#include <QTimer>
#include <algorithm>

struct MealPlanRequest {
    double totalCalories = 0;
    double proteinPercent = 25;
    double fatPercent = 30;
    double carbPercent = 45;
    double weeklyBudget = 2000;
    // 1 — Низкий, 2 — Средний, 3 — Высокий
    int varietyLevel = 2;
    QString likedFoods;
    QString dislikedFoods;
};

class MealPlanGenerator : public QObject
{
    Q_OBJECT

public:
    explicit MealPlanGenerator(QObject *parent = nullptr);
    void generate(const MealPlanRequest &req);
    void setPythonPath    (const QString &p) { m_pythonPath    = p; }
    void setBridgePath    (const QString &p) { m_bridgePath    = p; }
    void setSelectorPath  (const QString &p) { m_selectorPath  = p; }
    void setVerifierPath  (const QString &p) { m_verifierPath  = p; }
    void setGeneratorPath (const QString &p) { m_generatorPath = p; }

signals:
    void progressUpdated(const QString &message);
    void planReady(const QString &planText);
    void errorOccurred(const QString &error);

private slots:
    void onParserFinished          (int exitCode, QProcess::ExitStatus);
    void onLikedFoodsSearchFinished(int exitCode, QProcess::ExitStatus);
    void onSelectorFinished        (int exitCode, QProcess::ExitStatus);
    void onGeneratorFinished       (int exitCode, QProcess::ExitStatus);
    void onVerifierFinished        (int exitCode, QProcess::ExitStatus);

private:
    void runParser();
    void runLikedFoodsSearch();
    void runSelector();
    void runGenerator();
    void runVerifier();
    QProcess *launchProcess(const QStringList &args,
                            void (MealPlanGenerator::*slot)(int, QProcess::ExitStatus));

    MealPlanRequest m_req;
    QProcess  *m_process  = nullptr;
    QTimer    *m_watchdog = nullptr;
    QByteArray m_procOut;

    QString m_productsJsonPath;
    QString m_compactProductsJsonPath;
    QString m_planJsonPath;
    QJsonArray m_compactProducts;

    QString m_pythonPath    = "python";
    QString m_bridgePath    = "chizhik_bridge.py";
    QString m_selectorPath  = "meal_selector.py";
    QString m_verifierPath  = "meal_verifier.py";
    QString m_generatorPath = "generate_meal_plan.py";
};

#endif // MEALPLANGENERATOR_H
