#include "userprofilesetup.h"
#include <iostream>
#include <QApplication>
#include <QLabel>

int main(int argc, char *argv[])
{
    QApplication a(argc, argv);
    a.setApplicationName("ARM Nutritionist");
    a.setStyleSheet("QPushButton { background-color: red; }");
    UserProfileSetup w;
    w.show();
    return a.exec();
}


