#ifndef DATABASEMANAGER_H
#define DATABASEMANAGER_H
#include <QSqlDatabase>
#include <QString>
struct UserData {
    int id = -1;
    QString password;
    int gender = 0;
    int age = 0;
    double height = 0;
    double weight = 0;
    float activity = 0;
    int aim = 0;
    int totalCalorieIntake = 0;
};
class DatabaseManager {
public:
    explicit DatabaseManager(const QString &dbName = "users.db");
    bool init();
    // Возвращает true при успехе; данные кладёт в out
    bool findUser(const QString &username, UserData &out);
    bool registerUser(const QString &username, const QString &password, int &outId);
    bool saveParams(int id, int gender, int age, double height, double weight);
    bool saveActivityAndAim(int id, float activity, int aim);
    bool saveTotalCalories(int id, double totalCalorieIntake);
    QString lastError() const {
        return m_lastError;
    }
private:
    QSqlDatabase m_db;
    QString      m_lastError;
};
#endif // DATABASEMANAGER_H

