#include "CalorieCalculator.h"
#include <cmath>
double CalorieCalculator::calcMiffSJr(int gender, double weight, double height, int age, float activity, int aim)
{
    double cal = 0;
    if (gender == 1) {
        cal = 5 + (10 * weight) + (6.25 * height) - (5 * age);
    } else {
        cal = (10 * weight) + (6.25 * height) - (5 * age) - 161;
    }
    cal *= activity;
    cal += aim;
    return round(cal);
}
