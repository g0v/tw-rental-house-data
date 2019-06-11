import re

def clean_number(number_string: str):
    """
    Convert dirty string into number.
    Remove leading and trailing unrelated char and ignore ',' between number.
    """
    if number_string is None or number_string == '':
        return None
    number_string = '{}'.format(number_string)
    pure_number = re.sub('[^\\d.-]', '', number_string)

    if pure_number == '':
        # it could be '' if no digit included
        return None

    if pure_number.isdigit():
        return int(pure_number, base=10)

    return float(pure_number)
