#include "DatabaseManager.h"
#include <QSqlQuery>
#include <QSqlError>
#include <QDebug>
DatabaseManager::DatabaseManager(const QString &dbName)
{
    m_db = QSqlDatabase::addDatabase("QSQLITE");
    m_db.setDatabaseName(dbName);
}
bool DatabaseManager::init()
{
    if (!m_db.open()) {
        m_lastError = m_db.lastError().text();
        qDebug() << "Ошибка открытия БД:" << m_lastError;
        return false;
    }
    QSqlQuery query(m_db);
    QString createTableSQL =
        "CREATE TABLE IF NOT EXISTS users ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "username TEXT NOT NULL UNIQUE,"
        "password TEXT NOT NULL,"
        "gender INTEGER DEFAULT 0,"
        "age INTEGER DEFAULT 0,"
        "height REAL DEFAULT 0,"
        "weight REAL DEFAULT 0,"
        "activity REAL DEFAULT 0,"
        "aim INTEGER DEFAULT 0,"
        "totalCalorieIntake INTEGER DEFAULT 0"
        ")";
    if (!query.exec(createTableSQL)) {
        m_lastError = query.lastError().text();
        return false;
    }
    return true;
}
bool DatabaseManager::findUser(const QString &username, UserData &out)
{
    QSqlQuery q(m_db);
    q.prepare("SELECT id, password, height, weight, age, gender, aim, "
              "activity, totalCalorieIntake "
              "FROM users WHERE username = :username");
    q.bindValue(":username", username);
    if (!q.exec() || !q.next()) {
        m_lastError = q.lastError().text();
        return false;
    }
    out.id = q.value("id").toInt();
    out.password = q.value("password").toString();
    out.height = q.value("height").toDouble();
    out.weight = q.value("weight").toDouble();
    out.age = q.value("age").toInt();
    out.gender = q.value("gender").toInt();
    out.aim = q.value("aim").toInt();
    out.activity = q.value("activity").toFloat();
    out.totalCalorieIntake = q.value("totalCalorieIntake").toInt();
    return true;
}
bool DatabaseManager::registerUser(const QString &username, const QString &password, int &outId)
{
    QSqlQuery checkQuery(m_db);
    checkQuery.prepare("SELECT username FROM users WHERE username = :username");
    checkQuery.bindValue(":username", username);
    if (checkQuery.exec() && checkQuery.next()) {
        m_lastError = "Пользователь с таким именем уже существует.";
        return false;
    }
    QSqlQuery insertQuery(m_db);
    insertQuery.prepare(
        "INSERT INTO users (username, password) VALUES (:username, :password)");
    insertQuery.bindValue(":username", username);
    insertQuery.bindValue(":password", password);
    if (!insertQuery.exec()) {
        m_lastError = insertQuery.lastError().text();
        return false;
    }
    outId = insertQuery.lastInsertId().toInt();
    return true;
}
bool DatabaseManager::saveParams(int id, int gender, int age, double height, double weight)
{
    QSqlQuery q(m_db);
    q.prepare("UPDATE users SET gender=:gender, age=:age, ""height=:height, weight=:weight WHERE id=:id");
    q.bindValue(":gender", gender);
    q.bindValue(":age",    age);
    q.bindValue(":height", height);
    q.bindValue(":weight", weight);
    q.bindValue(":id",     id);
    if (!q.exec()) { m_lastError = q.lastError().text(); return false; }
    return true;
}
bool DatabaseManager::saveActivityAndAim(int id, float activity, int aim)
{
    QSqlQuery q(m_db);
    q.prepare("UPDATE users SET activity=:activity, aim=:aim WHERE id=:id");
    q.bindValue(":activity", activity);
    q.bindValue(":aim", aim);
    q.bindValue(":id", id);
    if (!q.exec()) {
        m_lastError = q.lastError().text();
        return false;
    }
    return true;
}
bool DatabaseManager::saveTotalCalories(int id, double totalCalorieIntake)
{
    QSqlQuery q(m_db);
    q.prepare("UPDATE users SET totalCalorieIntake=:totalCalorieIntake "
              "WHERE id=:id");
    q.bindValue(":totalCalorieIntake", totalCalorieIntake);
    q.bindValue(":id", id);
    if (!q.exec()) { m_lastError = q.lastError().text(); return false; }
    return true;
}
