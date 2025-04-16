#!/usr/bin/env python3
from operator import truediv

import pandas
from absl import app
from absl import flags
import os, tempfile
import webbrowser

from google.protobuf import text_format
from ortools.sat.python import cp_model
from pandas.compat.numpy.function import validate_sum
from pandas.core.array_algos.transforms import shift

_OUTPUT_PROTO = flags.DEFINE_string(
    "output_proto", "", "Output file to write the cp_model proto to."
)

html_header = '''<!DOCTYPE html>
<html>
<style>
table, th, td {
  border:1px solid black;
}
</style>
<body>

'''

html_footer = '''

</body>
</html>

'''

num_weeks = 4
week = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
shifts = ["IM", "M1", "M2", "IA", "A1", "A2", "A3", "N1", "N2"]

shift_groups = [
    ["M1", "M2", "A1", "A2", "A3", "N1", "N2"],
    ["IM", "IA"]
]

week_day_shifts = ["IA", "A1", "A2", "A3", "N1", "N2"]
holiday_shifts = ["IM", "M1", "M2", "IA", "A1", "A2", "A3","N1", "N2"]

levels = {
    "A": ["M1", "M2", "A1", "A2", "A3", "N1", "N2"],
    "B": ["M2", "A2", "A3", "N2", "IM", "IA"],
    "C": ["M2", "A3", "N2", "IM", "IA"],
    "D": ["M2", "A3", "IM", "IA"],
    "E": ["M2", "A3"]
}

day_parts = [
    ["IM", "M1", "M2"],
    ["IA", "A1", "A2", "A3"],
    ["N1", "N2"]
]

shift_categories = {

}

# Data
################################################################################
#start options
month_first_day = "Th"
month_days = 31
public_holidays = [1,]
prev_month_last_is_holiday = False
next_month_first_is_holiday = False
month_starts_with_internal = 1
hot_periods = []

#end options
################################################################################

employees = []

employees_stats = []

class EmployeeStat:
    def __init__(self):
        self.shifts_count = None
        self.nights_count = None
        self.holidays_count = None
        self.more_than_five = None
        self.more_than_four = None
        self.more_than_three = None
        self.more_than_one_night = None
        self.two_nights_on_four = None
        self.one_night_on_three = None

    def __str__(self):
        return f'more_than_three {self.more_than_three}, more_than_five {self.more_than_five},  two_nights {self.two_nights}, two_nights_on_four {self.two_nights_on_four}'

def is_holiday(d):
    if d == -1:
        return prev_month_last_is_holiday
    if d == month_days:
        return next_month_first_is_holiday

    first_day_index = week.index(month_first_day)
    if d + 1 in public_holidays:
        return True
    elif (d + first_day_index) % len(week) in [week.index("Sa"), week.index("Su")]:
        return True
    return False

def is_sunday(d):
    first_day_index = week.index(month_first_day)
    return (d + first_day_index) % len(week)  == week.index("Su")

def is_saturday(d):
    first_day_index = week.index(month_first_day)
    return (d + first_day_index) % len(week)  == week.index("Sa")

def is_other_holiday(d):
    return is_holiday(d) and not is_saturday(d) and not is_sunday(d)

def get_night_shifts():
    return [shifts.index(x) for x in day_parts[2]]

def get_employee_name(e):
    return employees[e][0]

def get_employee_level(e):
    return employees[e][1]

def get_employee_capable_shifts(e):
    return levels[employees[e][1]]

def get_employee_min_shifts(e):
    return employees[e][2][0]

def get_employee_max_shifts(e):
    return employees[e][2][1]

def get_employee_preference(e,d,i):
    return employees[e][3][d][i]

def prefered_nights(e):
    count = 0
    for d in range(month_days):
        if get_employee_preference(e,d,2) == "P" or get_employee_preference(e,d,2) == "WP":
            if get_employee_preference(e,d,1) != "P" and get_employee_preference(e,d,1) != "WP":
                if get_employee_preference(e, d, 0) != "P" and get_employee_preference(e, d, 0) != "WP":
                    count += 1
    return count

def get_pos_prefs(e):
    count = 0
    for d in range(month_days):
        for i in range(3):
            if get_employee_preference(e,d,i) == "WP":
                count += 1
    return count

def get_neg_prefs(e):
    count = 0
    for d in range(month_days):
        for i in range(3):
            if get_employee_preference(e,d,i) == "WN":
                count += 1
    return count

def get_neg(e):
    count = 0
    for d in range(month_days):
        for i in range(3):
            if get_employee_preference(e,d,i) == "N":
                count += 1
    return count

def get_pos(e):
    count = 0
    for d in range(month_days):
        for i in range(3):
            if get_employee_preference(e,d,i) == "P":
                count += 1
    return count

def prefers_nights(e):
    return prefered_nights(e) > 10

def is_night_dp_idx(idx):
    return idx == 2

def is_night_shift(s):
    return shifts[s] in day_parts[2]

def get_day_part_shifts(part_idx):
    return [i for i in range(len(shifts)) if shifts[i] in day_parts[part_idx]]

def validate_input():
    valid = True

    if not month_first_day in week:
        print("wrong day")
        valid = False
    if month_days > 31 or month_days < 28:
        print("wrong month days")
        valid = False

    for l in levels:
        for s in levels[l]:
            if not s in shifts:
                print("wrong shift in level")
                valid = False
    for s in week_day_shifts:
        if not s in shifts:
            print("wrong weekday shift")
            valid = False
    for s in holiday_shifts:
        if not s in shifts:
            print("wrong holiday shift")
            valid = False
    for h in public_holidays:
        if h > month_days or h <= 0:
            print("wrong holiday")
            valid = False
    for g in shift_groups:
        for s in g:
            if not s in shifts:
                print("wrong shift in group")
                valid = False

    for dp in day_parts:
        for s in dp:
            if not s in shifts:
                print("wrong day part")
                valid = False

    for s in shifts:
        c = 0
        for dp in day_parts:
            for sdp in dp:
                if s == sdp:
                    c += 1
        if c != 1:
            print("wrong day part2" + str(c))
            valid = False

    for e in employees:
        if e[1] not in levels:
            valid = False
            print ("not in levels")
        if len(e[2]) != 2:
            valid = False
            print("invalid shift num pref")
        if len(e[3]) != month_days:
            valid = False
            print("invalid shift num pref days")
        for day_pref in e[3]:
            if len(day_pref)!=3:
                valid = False
                print("invalid shift num pref days len")
            for prf in day_pref:
                if prf not in ["I", "WP", "P", "WN", "N"]:
                    valid = False
                    print ("wrong pref str")

    return valid

def format_input(data):
    global employees
    employees = []

    for row in data:
        out = []
        out.append(row[0])
        out.append(row[1])
        out.append([int(row[2]), int(row[3])])
        prefs = []
        count = 0
        for i in range(4, len(row), 3):
            count += 1
            prefs.append([row[i],row[i+1],row[i+2]])
        out.append(prefs)
        employees.append(out)
        employees_stats.append(EmployeeStat())

        if month_days != count:
            print("wrong pref data")
            employees = []
            return None

def as_html_table(lines):
    out = r"<table>"

    for line in lines:
        out += '\n' + r'<tr>' + '\n  '
        for row in line:
            out += r'<td>' + str(row) + r'</td>'
        out += '\n' + r'</tr>'
    out += "\n" + r"</table>"
    return out

def html_bold(s):
    return r'<b>' + str(s) + r'</b>'

def html_bold_if(s, cond):
    if cond:
        return html_bold(s)
    else:
        return s

def html_mark(s):
    return r'<mark>' + str(s) + r'</mark>'

def html_mark_if(s, cond):
    if cond:
        return html_mark(s)
    else:
        return s

def in_brackets_if(s, cond):
    if cond:
        return '[' + s + ']'
    else:
        return s

def print_solution(solver, status, work):
    num_employees = len(employees)
    num_shifts = len(shifts)
    first_day_index = week.index(month_first_day)

    if status == cp_model.OPTIMAL:
        print("OPTIMAL")
    output = []
    header = ["", ""]
    header += shifts
    output.append(header)
    for d in range(month_days):
        line = []
        line.append(html_bold_if(str(d + 1), is_holiday(d)))
        line.append(html_bold_if(week[(d + first_day_index) % 7],is_holiday(d)))
        for s in range(num_shifts):
            shift_given = False
            for e in range(num_employees):
                if solver.boolean_value(work[e, s, d]):
                    line.append(html_bold_if(get_employee_name(e), is_holiday(d)))
                    shift_given = True
            if not shift_given:
                line.append("")
        output.append(line)
    # print(tabulate(output, tablefmt="html"))

    out2 = []
    header2 = ["NAME", "SHIFTS", "NIGHTS", "HOLIDAYS", "Sa", "Su", "othr_ho", "days"]
    out2.append(header2)
    for e in range(num_employees):
        line = []
        sft = 0
        nght = 0
        hdy = 0
        su = 0
        sa = 0
        oh = 0
        days = []
        line.append(f"{get_employee_name(e)} - {get_employee_level(e)}[{get_employee_min_shifts(e)},{get_employee_max_shifts(e)}]")
        for d in range(month_days):
            for s in range(num_shifts):
                if solver.boolean_value(work[e, s, d]):
                    #days.append(in_brackets_if( html_bold_if(str(d+1),is_holiday(d)), is_night_shift(s)))
                    days.append(html_bold_if(in_brackets_if(str(d+1),is_night_shift(s)),is_holiday(d)))
                    sft += 1
                    if is_holiday(d):
                        hdy +=1
                    if is_saturday(d):
                        sa += 1
                    if is_sunday(d):
                        su += 1
                    if is_other_holiday(d):
                        oh += 1
                    if s in get_night_shifts():
                        nght += 1
        line.append(sft)
        line.append(nght)
        line.append(hdy)
        line.append(sa)
        line.append(su)
        line.append(oh)
        line.append(','.join(days))

        out2.append(line)

    tmp = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.html')
    try:
        print(tmp.name)
        tmp.write(html_header)
        tmp.write(as_html_table(output))
        tmp.write('<br><br>')
        tmp.write(as_html_table(out2))
        tmp.write(html_footer)
    finally:
        tmp.close()
        webbrowser.open('file://' + os.path.realpath(tmp.name))

def can_do_nights(e):
    for x in day_parts[2]:
        if x in get_employee_capable_shifts(e):
            return True
    return False


def solve_shift_scheduling(output_proto: str):
    """Solves the shift scheduling problem."""
    num_employees = len(employees)
    num_shifts = len(shifts)
    first_day_index = week.index(month_first_day)

    model = cp_model.CpModel()

    if not validate_input():
        return
########################################################################
# Basic Rules
########################################################################
    cost_literals = []
    cost_coefficients = []

    work = {}
    for e in range(num_employees):
        for s in range(num_shifts):
            for d in range(month_days):
                work[e, s, d] = model.new_bool_var(f"work{e}_{s}_{d}")

    # #Exactly one shift per day
    # for e in range(num_employees):
    #     for d in range(month_days):
    #         model.add_at_most_one(work[e, s, d] for s in range(num_shifts))

    # Exactly one shift per 2 days
    for e in range(num_employees):
        for d in range(month_days - 1):
            model.add_at_most_one(work[e, s, d_] for d_ in [d, d+1] for s in range(num_shifts))

    #not close nights
    close_range = 2
    for e in range(num_employees):
        for d in range(month_days - close_range):
            model.add_at_most_one(work[e, s, d_] for d_ in range(d, d + close_range + 1) for s in get_night_shifts())

    #exclude shifts based to employee capability
    for e in range(num_employees):
        for s in range(num_shifts):
            for d in range(month_days):
                if shifts[s] not in get_employee_capable_shifts(e):
                    model.add(work[e, s, d] == False)

    #force all shifts to be covered
    total_shifts = 0
    for d in range(month_days):
            if is_holiday(d):
                day_shifts = set(holiday_shifts)
            else:
                day_shifts = set(week_day_shifts)
            day_shifts = day_shifts.intersection(set(shift_groups[(d + month_starts_with_internal) % len(shift_groups)]))

            for s in range(num_shifts):
                works = [work[e, s, d] for e in range(num_employees)]
                if shifts[s] in day_shifts:
                    model.add_exactly_one(works)
                    total_shifts += 1
                else:
                    for zero_work in works:
                        model.add(zero_work == False)

    #shifts num per employee
    for e in range(num_employees):
        employees_stats[e].shifts_count = model.new_int_var(get_employee_min_shifts(e), get_employee_max_shifts(e), f"shifts_count({e})")
        employee_works = [work[e, s, d] for s in range(num_shifts) for d in range(month_days)]
        model.add(employees_stats[e].shifts_count == sum(employee_works))

        max_holidays = 3
        if not prefers_nights(e):
            max_nights = 2
        else:
            max_nights = get_employee_max_shifts(e)

        employees_stats[e].nights_count = model.new_int_var(0, max_nights,f"nights_count({e})")
        night_works = [work[e, s, d] for d in range(month_days) for s in range(num_shifts) if is_night_shift(s)]
        model.add(employees_stats[e].nights_count == sum(night_works))

        employees_stats[e].holidays_count = model.new_int_var(0, max_holidays,f"holidays_count({e})")
        holiday_works = [work[e, s, d] for s in range(num_shifts) for d in range(month_days)  if is_holiday(d)]
        model.add(employees_stats[e].holidays_count == sum(holiday_works))

        employees_stats[e].more_than_six = model.new_bool_var(f"e_{e}_more_than_six")
        model.add(employees_stats[e].shifts_count > 6).only_enforce_if(employees_stats[e].more_than_six)
        model.add(employees_stats[e].shifts_count <= 6).only_enforce_if(~employees_stats[e].more_than_six)

        employees_stats[e].more_than_five = model.new_bool_var(f"e_{e}_more_than_five")
        model.add(employees_stats[e].shifts_count > 5).only_enforce_if(employees_stats[e].more_than_five)
        model.add(employees_stats[e].shifts_count <= 5).only_enforce_if(~employees_stats[e].more_than_five)

        employees_stats[e].more_than_four = model.new_bool_var(f"e_{e}_more_than_four")
        model.add(employees_stats[e].shifts_count > 4).only_enforce_if(employees_stats[e].more_than_four)
        model.add(employees_stats[e].shifts_count <= 4).only_enforce_if(~employees_stats[e].more_than_four)

        employees_stats[e].more_than_three = model.new_bool_var(f"e_{e}_more_than_three")
        model.add(employees_stats[e].shifts_count > 3).only_enforce_if(employees_stats[e].more_than_three)
        model.add(employees_stats[e].shifts_count <= 3).only_enforce_if(~employees_stats[e].more_than_three)

        employees_stats[e].more_than_two = model.new_bool_var(f"e_{e}_more_than_two")
        model.add(employees_stats[e].shifts_count > 2).only_enforce_if(employees_stats[e].more_than_two)
        model.add(employees_stats[e].shifts_count <= 2).only_enforce_if(~employees_stats[e].more_than_two)

        employees_stats[e].more_than_one_night = model.new_bool_var(f"e_{e}_more_than_one_night")
        model.add(employees_stats[e].nights_count > 1).only_enforce_if(employees_stats[e].more_than_one_night)
        model.add(employees_stats[e].nights_count <= 1).only_enforce_if(~employees_stats[e].more_than_one_night)

        employees_stats[e].has_night = model.new_bool_var(f"e_{e}_has_night")
        model.add(employees_stats[e].nights_count > 0).only_enforce_if(employees_stats[e].has_night)
        model.add(employees_stats[e].nights_count <= 0).only_enforce_if(~employees_stats[e].has_night)

        employees_stats[e].more_than_two_holidays = model.new_bool_var(f"e_{e}_more_than_two_holidays")
        model.add(employees_stats[e].holidays_count > 2).only_enforce_if(employees_stats[e].more_than_two_holidays)
        model.add(employees_stats[e].holidays_count <= 2).only_enforce_if(~employees_stats[e].more_than_two_holidays)

        # maybe needed to avoid  meaningless search
        # model.add_implication(employees_stats[e].more_than_six, employees_stats[e].more_than_five)
        # model.add_implication(employees_stats[e].more_than_five, employees_stats[e].more_than_four)
        # model.add_implication(employees_stats[e].more_than_four, employees_stats[e].more_than_three)
        # model.add_implication(employees_stats[e].more_than_three, employees_stats[e].more_than_two)
        #
        # model.add_implication(~employees_stats[e].more_than_two, ~employees_stats[e].more_than_three)
        # model.add_implication(~employees_stats[e].more_than_three, ~employees_stats[e].more_than_four)
        # model.add_implication(~employees_stats[e].more_than_four, ~employees_stats[e].more_than_five)
        # model.add_implication(~employees_stats[e].more_than_five, ~employees_stats[e].more_than_six)
        #
        # model.add_implication(employees_stats[e].more_than_one_night, employees_stats[e].has_night)
        # model.add_implication(~employees_stats[e].has_night, ~employees_stats[e].more_than_one_night)

        model.add(employees_stats[e].shifts_count >= employees_stats[e].nights_count)
        model.add(employees_stats[e].shifts_count >= employees_stats[e].holidays_count)

        #night rules
        if can_do_nights(e) and not prefers_nights(e):
            model.add_implication(employees_stats[e].has_night, employees_stats[e].more_than_two)

            employees_stats[e].two_nights_on_four = model.new_bool_var(f"e_{e}_two_nights_on_four")
            model.add_bool_or(~employees_stats[e].more_than_one_night, employees_stats[e].more_than_four, employees_stats[e].two_nights_on_four)
            cost_literals.append(employees_stats[e].two_nights_on_four)
            cost_coefficients.append(100)

            employees_stats[e].one_night_on_three = model.new_bool_var(f"e_{e}_one_night_on_three")
            model.add_bool_or(~employees_stats[e].has_night, employees_stats[e].more_than_three, employees_stats[e].one_night_on_three)
            cost_literals.append(employees_stats[e].one_night_on_three)
            cost_coefficients.append(70)
        elif can_do_nights(e):
            print("prefers nights " + str(e) + " " + str(prefered_nights(e)))

        #holiday_rules
        model.add(employees_stats[e].holidays_count <= 2).only_enforce_if(employees_stats[e].more_than_six)
        if get_employee_level(e) == 'A':
            model.add(employees_stats[e].holidays_count <= 2).only_enforce_if(~employees_stats[e].more_than_three)
        else:
            model.add(employees_stats[e].holidays_count <= 2).only_enforce_if(~employees_stats[e].more_than_four)

        if get_employee_level(e) == 'A':
            employees_stats[e].class_a_too_much_holidays = model.new_bool_var(f"e_{e}_class_a_too_much_holidays")
            model.add_bool_or(~employees_stats[e].more_than_four, ~employees_stats[e].more_than_two_holidays, employees_stats[e].class_a_too_much_holidays)
            cost_literals.append(employees_stats[e].class_a_too_much_holidays)
            cost_coefficients.append(30)

        employees_stats[e].three_holidays_less_six = model.new_bool_var(f"e_{e}_three_holidays_less_six")
        model.add_bool_or(~employees_stats[e].more_than_two_holidays, employees_stats[e].more_than_five ,employees_stats[e].three_holidays_less_six)
        cost_literals.append(employees_stats[e].three_holidays_less_six)
        cost_coefficients.append(80)

        cost_literals.append(employees_stats[e].more_than_six)
        cost_coefficients.append(-30)

    #positives - negatives
    for e in range(num_employees):
        pos_prefs = get_pos_prefs(e)
        neg_prefs = get_neg_prefs(e)
        negs = get_neg(e)
        pos = get_pos(e)

        for d in range(month_days):
            for dp_idx in range(len(day_parts)):
                employee_works = [work[e, s, d] for s in get_day_part_shifts(dp_idx)]

                slot_pref = get_employee_preference(e, d, dp_idx)

                if slot_pref == "P":
                    model.add_exactly_one(employee_works)

                if slot_pref == "N":
                    for w in employee_works:
                        model.add(w == 0)

                if slot_pref == "WN" or slot_pref == "WP":
                    name = f"worked_{e}_{d}_{dp_idx}"
                    worked = model.new_bool_var(name)
                    employee_works.append(~worked)
                    model.add_exactly_one(employee_works)
                    cost_literals.append(worked)

                    avail_days = (3*month_days - neg_prefs - negs - pos_prefs - pos) //3
                    weight = avail_days // 2
                    if weight <= 0:
                        weight = 1
                    if slot_pref == "WN":
                        cost_coefficients.append(weight)
                    else:
                        if is_night_dp_idx(dp_idx) and prefers_nights(e):
                            weight *= 3
                        cost_coefficients.append(-weight)


    #shifts spread
    window_size = 5
    max_shifts_on_window = 2
    for e in range(num_employees):
        if (get_neg(e) + get_neg_prefs(3)) < 10 * 3:
            employees_stats[e].exceeds_wdw_limits = []
            for d in range(month_days - window_size):
                shifts_count = model.new_int_var(0, window_size, f"window_e_{e}_d_{d}")
                works = [work[e, s, d1] for d1 in range(d, d +window_size) for s in range(num_shifts)]
                model.add(shifts_count == sum(works))
                employees_stats[e].exceeds_wdw_limit = model.new_bool_var(f"e_{e}_{d}_exceeds_wdw_lmt")
                employees_stats[e].exceeds_wdw_limits.append(employees_stats[e].exceeds_wdw_limit)
                model.add(shifts_count > max_shifts_on_window).only_enforce_if(employees_stats[e].exceeds_wdw_limit)
                model.add(shifts_count <= max_shifts_on_window).only_enforce_if(~employees_stats[e].exceeds_wdw_limit)
                cost_literals.append(employees_stats[e].exceeds_wdw_limit)
                cost_coefficients.append(8)

    # #
    # window2_size = 5
    # shifts_on_window2 = 2
    # for e in range(num_employees):
    #     for d in range(month_days - window2_size):
    #         shifts_count = model.new_int_var(0, shifts_on_window2, f"window2_e_{e}_d_{d}")
    #         works = [work[e, s, d1] for d1 in range(d, d +window2_size) for s in range(num_shifts)]
    #         model.add(shifts_count == sum(works))
    #

    #hot periods
    for e in range(num_employees):
        e_hot_periods=[]
        for h in range(len(hot_periods)):
            hot_works=[]
            for d1 in hot_periods[h]:
                d = d1 - 1
                for s in range(num_shifts):
                    hot_works.append(work[e, s, d])
            hot_work_var = model.new_bool_var(f"hot_work_e_{e}_h_{h}")
            model.add(sum(hot_works) > 0).only_enforce_if(hot_work_var)
            model.add(sum(hot_works) == 0).only_enforce_if(~hot_work_var)
            e_hot_periods.append(hot_work_var)
        model.add_at_most_one(e_hot_periods)


    avg_shifts = total_shifts // len(employees)
    rem_shifts = total_shifts % len(employees)


    print("avg shifts: " + str(avg_shifts) + " " + str(rem_shifts))
    print("total shifts " + str(total_shifts))

    # Objective
    model.minimize(
        #sum(cost_literals[i] * cost_coefficients[i] for i in range(len(cost_literals)))
        cp_model.LinearExpr.weighted_sum(cost_literals, cost_coefficients)
        #+
        #sum(obj_int_vars[i] * obj_int_coeffs[i] for i in range(len(obj_int_vars)))
    )

    if output_proto:
        print(f"Writing proto to {output_proto}")
        with open(output_proto, "w") as text_file:
            text_file.write(str(model))

    # Solve the model.
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 20
    #solver.parameters.log_search_progress = True
    #solver.parameters.enumerate_all_solutions = True
    #solver.parameters.num_search_workers = 8
    #solver.parameters.log_to_stdout = True
    #solver.parameters.linearization_level = 0
    #solver.parameters.cp_model_presolve = True
    #solver.parameters.cp_model_probing_level = 0

    solution_printer = cp_model.ObjectiveSolutionPrinter()
    status = solver.solve(model, solution_printer)

    print("Status = %s" % solver.status_name(status))

    print("Statistics")
    print("  - conflicts : %i" % solver.num_conflicts)
    print("  - branches  : %i" % solver.num_branches)
    print("  - wall time : %f s" % solver.wall_time)
    print("  - number of solutions found: %i" % solution_printer.solution_count())

    # Print solution.
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        print("SOLVED")
        print_solution(solver, status, work)
    else:
        print("NOT SOLVED :-(")

    if status == cp_model.INFEASIBLE:
        # print infeasible boolean variables index
        print('SufficientAssumptionsForInfeasibility = 'f'{solver.SufficientAssumptionsForInfeasibility()}')

        # print infeasible boolean variables
        infeasibles = solver.SufficientAssumptionsForInfeasibility()
        for i in infeasibles:
            print('Infeasible constraint: %d' % model.GetBoolVarFromProtoIndex(i))

def main(_):
    data = pandas.read_csv('data.may.csv').fillna("I")


    # Display the modified DataFrame
    #print(data.head())
    list_data = data.values.tolist()
    format_input(list_data)

    for e in employees:
        print(e)
    solve_shift_scheduling(_OUTPUT_PROTO.value)


if __name__ == "__main__":
    app.run(main)
