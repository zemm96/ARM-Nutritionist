#include "userprofilesetup.h"
#include "ui_userprofilesetup.h"
#include "CalorieCalculator.h"
#include <QDebug>
#include <QMessageBox>

UserProfileSetup::UserProfileSetup(QWidget *parent)
    : QMainWindow(parent)
    , ui(new Ui::UserProfileSetup)
    , m_db("users.db")
{
    ui->setupUi(this);
    this->setFixedSize(900, 760);
    m_db.init();

    // Размещаем MealPlanWidget внутри page_7 (index 6) — пустой страницы из .ui
    m_planWidget = new MealPlanWidget(ui->page_7);
    QVBoxLayout *planLayout = new QVBoxLayout(ui->page_7);
    planLayout->setContentsMargins(0, 0, 0, 0);
    planLayout->addWidget(m_planWidget);

    // «Назад» из плана → возврат на центральный экран (index 5)
    connect(m_planWidget, &MealPlanWidget::backRequested, this, [this]() {
        ui->stackedWidget->setCurrentIndex(5);
    });
}

UserProfileSetup::~UserProfileSetup()
{
    delete ui;
}
void UserProfileSetup::on_backBtn3_clicked() {
    ui->stackedWidget->setCurrentIndex(0);
}
void UserProfileSetup::on_userTextBtn_clicked()
{
    QString login = ui->loginLineEdit->text().trimmed();
    QString password = ui->passwordLineEdit->text();
    if (login.isEmpty() || password.isEmpty()) {
        QMessageBox::warning(this, "Ошибка", "Заполните все поля!");
        return;
    }
    UserData user;
    if (!m_db.findUser(login, user)) {
        QMessageBox::warning(this, "Ошибка",
                             "Пользователь с таким логином не найден.");
        ui->passwordLineEdit->clear();
        return;
    }
    if (user.password != password) {
        QMessageBox::warning(this, "Ошибка", "Неверный пароль.");
        ui->passwordLineEdit->clear();
        ui->passwordLineEdit->setFocus();
        return;
    }
    // Загружаем данные пользователя
    currId = user.id;
    height = user.height;
    weight = user.weight;
    age = user.age;
    gender= user.gender;
    aim = user.aim;
    activity = user.activity;
    totalCalorieIntake = user.totalCalorieIntake;
    extra_cal          = aim;   // синхронизируем, чтобы on_mealPlanBtn_clicked работал корректно
    if (height > 0 && weight > 0 && age > 0
        && (gender == 0 || gender == 1)
        && (aim == -300 || aim == 300 || aim == 0)
        && (activity > 0 && activity <= 1.9)
        && totalCalorieIntake > 0)
    {
        if (aim == -300) percent = "  Белки - 30%   Жиры - 30%   Углеводы - 40%";
        else if (aim ==  300) percent = "  Белки - 20%   Жиры - 25%   Углеводы - 55%";
        else percent = "  Белки - 25%   Жиры - 30%   Углеводы - 45%";

        ui->cal_label2->setText(QString::number(totalCalorieIntake));
        ui->PercentLabel2->setText(percent);
        ui->stackedWidget->setCurrentIndex(5);
    } else {
        // Данные не заполнены → мастер настройки
        ui->stackedWidget->setCurrentIndex(1);
    }
}

void UserProfileSetup::on_makeAccB_clicked()
{
    ui->stackedWidget->setCurrentIndex(4);
}

void UserProfileSetup::on_registerAcc_clicked()
{
    QString login_reg           = ui->login->text().trimmed();
    QString password_reg        = ui->password->text();
    QString password_reg_repeat = ui->passwordRepeat->text();

    if (login_reg.isEmpty() || password_reg.isEmpty() || password_reg_repeat.isEmpty()) {
        QMessageBox::warning(this, "Ошибка", "Логин и пароль не могут быть пустыми.");
        return;
    }
    if (password_reg != password_reg_repeat) {
        QMessageBox::warning(this, "Ошибка", "Пароли не совпадают.");
        return;
    }
    if (!m_db.registerUser(login_reg, password_reg, currId)) {
        QMessageBox::warning(this, "Ошибка", m_db.lastError());
        return;
    }

    ui->stackedWidget->setCurrentIndex(1);
}

void UserProfileSetup::on_nextBtn1_clicked()
{
    bool isMale   = ui->malerb->isChecked();
    bool isFemale = ui->femalerb->isChecked();
    age           = ui->ageBox->value();

    if (!isMale && !isFemale) {
        QMessageBox::warning(this, "Ошибка", "Выберите пол!");
        return;
    }
    if (age <= 0 || age > 130) {
        QMessageBox::warning(this, "Ошибка", "Введите корректный возраст!");
        return;
    }

    QString heigText = ui->heightEdit->toPlainText().trimmed();
    QString weigText = ui->weightEdit->toPlainText().trimmed();

    if (heigText.isEmpty() || weigText.isEmpty()) {
        QMessageBox::warning(this, "Ошибка", "Заполните все поля!");
        return;
    }

    bool ok;
    height = heigText.toDouble(&ok);
    if (!ok || height <= 0 || height > 280) {
        QMessageBox::warning(this, "Ошибка", "Введите корректный рост!");
        return;
    }
    weight = weigText.toDouble(&ok);
    if (!ok || weight <= 0 || weight > 650) {
        QMessageBox::warning(this, "Ошибка", "Введите корректный вес!");
        return;
    }
    gender = isMale ? 1 : 0;
    if (!m_db.saveParams(currId, gender, age, height, weight)) {
        QMessageBox::critical(this, "Ошибка",
                              "Не удалось сохранить данные: " + m_db.lastError());
        return;
    }
    ui->stackedWidget->setCurrentIndex(2);
}
void UserProfileSetup::on_nextBtn2_clicked()
{
    if      (ui->SedentaryJob->isChecked())    activity = 1.2f;
    else if (ui->EasyWorkout->isChecked())     activity = 1.375f;
    else if (ui->AverageWorkout->isChecked())  activity = 1.55f;
    else if (ui->IntenseWorkout->isChecked())  activity = 1.725f;
    else if (ui->PowerfulWorkout->isChecked()) activity = 1.9f;
    else {
        QMessageBox::warning(this, "Ошибка", "Выберите уровень активности!");
        return;
    }

    if      (ui->WeightLoss->isChecked())   { extra_cal = -300; percent = "  Белки - 30%   Жиры - 30%   Углеводы - 40%"; }
    else if (ui->Maintenance->isChecked())  { extra_cal =    0; percent = "  Белки - 25%   Жиры - 30%   Углеводы - 45%"; }
    else if (ui->WeightGain->isChecked())   { extra_cal =  300; percent = "  Белки - 20%   Жиры - 25%   Углеводы - 55%"; }
    else {
        QMessageBox::warning(this, "Ошибка", "Выберите цель (похудение / поддержание / набор)!");
        return;
    }

    aim = extra_cal;   // синхронизируем класс-поле

    if (!m_db.saveActivityAndAim(currId, activity, extra_cal)) {
        QMessageBox::critical(this, "Ошибка",
                              "Не удалось сохранить данные: " + m_db.lastError());
        return;
    }

    // Переходим на страницу любимых/нелюбимых блюд (index 3)
    ui->stackedWidget->setCurrentIndex(3);
}
// Страница 3 → 5: расчёт КБЖУ → центральный экран
void UserProfileSetup::on_nextBtn3_clicked()
{
    double cal = CalorieCalculator::calcMiffSJr(
        gender, weight, height, age, activity, extra_cal);

    totalCalorieIntake = cal;   // сохраняем в поле класса

    if (!m_db.saveTotalCalories(currId, cal)) {
        QMessageBox::critical(this, "Ошибка",
                              "Не удалось сохранить калории: " + m_db.lastError());
    }

    // Показываем центральный экран
    ui->cal_label2->setText(QString::number(static_cast<int>(cal)));
    ui->PercentLabel2->setText(percent);
    ui->stackedWidget->setCurrentIndex(5);
}
// Кнопки «Назад»
void UserProfileSetup::on_backBtn1_clicked()
{
    ui->stackedWidget->setCurrentIndex(1);
}

void UserProfileSetup::on_backBtn2_clicked()
{
    ui->stackedWidget->setCurrentIndex(2);
}
// Центральный экран → генерация плана питания
void UserProfileSetup::on_mealPlanBtn_clicked()
{
    // Бюджет на неделю
    bool ok;
    double weeklyBudget = ui->BudgetlineEdit->text().replace(',', '.').toDouble(&ok);
    if (!ok || weeklyBudget <= 0) {
        QMessageBox::warning(this, "Ошибка",
                             "Введите бюджет на неделю (в рублях).");
        ui->BudgetlineEdit->setFocus();
        return;
    }
    // Уровень разнообразия (lo=1, radioButton_7=2, radioButton_8=3)
    int varietyLevel = 2; // средний по умолчанию
    if      (ui->lo->isChecked())            varietyLevel = 1;
    else if (ui->radioButton_7->isChecked()) varietyLevel = 2;
    else if (ui->radioButton_8->isChecked()) varietyLevel = 3;
    // Любимые и нелюбимые блюда из страницы 3 (page_4 в .ui)
    QString liked    = ui->Loved->toPlainText().trimmed();
    QString disliked = ui->Unloved->toPlainText().trimmed();
    // КБЖУ-проценты на основе текущей цели
    double prot = 25, fat = 30, carb = 45;
    if      (extra_cal == -300) { prot = 30; fat = 30; carb = 40; }
    else if (extra_cal ==  300) { prot = 20; fat = 25; carb = 55; }
    // Передаём данные в виджет плана
    m_planWidget->setUserCalories(totalCalorieIntake, prot, fat, carb);
    m_planWidget->setParams(weeklyBudget, varietyLevel, liked, disliked);
    ui->stackedWidget->setCurrentIndex(6); // page_7
}
