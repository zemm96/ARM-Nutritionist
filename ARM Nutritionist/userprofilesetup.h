#ifndef USERPROFILESETUP_H
#define USERPROFILESETUP_H

#include <QtWidgets>
#include <QMainWindow>
#include "mealplanwidget.h"
#include "databasemanager.h"

QT_BEGIN_NAMESPACE
namespace Ui { class UserProfileSetup; }
QT_END_NAMESPACE

class UserProfileSetup : public QMainWindow
{
    Q_OBJECT

private slots:
    void on_userTextBtn_clicked();
    void on_nextBtn1_clicked();
    void on_makeAccB_clicked();
    void on_registerAcc_clicked();
    void on_backBtn1_clicked();
    void on_backBtn2_clicked();
    void on_nextBtn2_clicked();
    void on_nextBtn3_clicked();
    void on_mealPlanBtn_clicked();
    void on_backBtn3_clicked();

public:
    explicit UserProfileSetup(QWidget *parent = nullptr);
    ~UserProfileSetup();

private:
    Ui::UserProfileSetup *ui;
    DatabaseManager m_db;

    // Данные пользователя
    int currId = -1;
    int gender = 0;
    int age = 0;
    int aim = 0;       // загружается из БД при логине
    int extra_cal = 0;
    double weight = 0;
    double height = 0;
    double totalCalorieIntake = 0;
    float activity = 0;
    QString percent;

    // Виджет плана питания (размещён внутри page_7, index 6)
    MealPlanWidget *m_planWidget = nullptr;
};

#endif // USERPROFILESETUP_H
