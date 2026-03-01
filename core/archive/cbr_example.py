import csv
import json
from types import SimpleNamespace

import requests


def save_json_to_file(response, filename):
    """Сохраняет ответ API в JSON-файл"""
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(response.json(), f, ensure_ascii=False, indent=4)


def export_data_to_csv(data, filename="data.csv"):
    """Экспортирует данные в CSV (аналог PivotExport.ExportDataToCSV)"""
    # если данные — объект SimpleNamespace, превращаем в словарь
    if isinstance(data, SimpleNamespace):
        data = data.__dict__

    # если это список объектов
    if isinstance(data, list):
        if len(data) == 0:
            print("Нет данных для экспорта")
            return
        keys = data[0].__dict__.keys()
        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            for item in data:
                writer.writerow(item.__dict__)
    else:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    print(f"Данные успешно сохранены в {filename}")


print("Пример работы с API Сервиса получения данных")
BASE_URL = 'http://www.cbr.ru/dataservice'  # источник данных

# необходимо получить все параметры для основного запроса /data
# для этого последовательно получаем данные справочников


print("**** Список публикаций ****")
response = requests.get(f"{BASE_URL}/publications")
save_json_to_file(response, "publications.json")  # сохраяеем данные запроса в файл (для теста)
publicationObject = response.json(object_hook=lambda d: SimpleNamespace(**d))

for pbl in publicationObject:
    print(f"id:{pbl.id} title:{pbl.category_name} {' - NoActive' if pbl.NoActive else ''}")

publId = -1  # id публикации
while True:
    try:
        publId = int(input("Введите id публикации:"))
        selPublItem = next((e for e in publicationObject if e.id == publId), None)
        if not selPublItem == None and not selPublItem.NoActive:
            break
        else:
            print("Данного id не существует либо раздел не может быть выбран (NoActive)")
    except ValueError:
        print("ошибка! id должен быть числом...")

print(f"Для id публикации:{publId} нужно выбрать показатель из списка")
print("**** Список показателей  ****")

responseDS = requests.get(f"{BASE_URL}/datasets?publicationId={publId}")
save_json_to_file(response, "datasets.json")  # сохраяеем данные запроса в файл (для теста)
DSObject = responseDS.json(object_hook=lambda d: SimpleNamespace(**d))

for dsItem in DSObject:
    print(f"id:{dsItem.id}, title:{dsItem.name}")

dsId = -1  # id показателя
while True:
    try:
        dsId = int(input("Введите id показателя:"))
        selDSItem = next((e for e in DSObject if e.id == dsId), None)
        if selDSItem is None:
            print("Данного id не существует")
        else:
            currentTypeVal = selDSItem.type
            break
    except ValueError:
        print("ошибка! id должен быть числом...")

print("currentTypeVal", currentTypeVal)
melId = -1  # id разреза

if currentTypeVal == 1:
    print("**** Список разрезов  ****")
    responseME = requests.get(f"{BASE_URL}/measures?datasetId={dsId}")
    save_json_to_file(response, "measures.json")  # сохраяеем данные запроса в файл (для теста)
    MEObject = responseME.json(object_hook=lambda d: SimpleNamespace(**d)).measure
    for meItem in MEObject:
        print(f"id:{meItem.id}, title:{meItem.name}")
    while True:
        try:
            melId = int(input("Введите id разреза:"))
            selMeItem = next((e for e in MEObject if e.id == melId), None)
            if selMeItem is None:
                print("Данного id не существует")
            else:
                break
        except ValueError:
            print("ошибка! id должен быть числом...")
else:
    print("У этого показателя нет разрезов")

yaersParams = {'measureId': melId, 'datasetId': dsId}
responseYears = requests.get(f"{BASE_URL}/years", params=yaersParams)
save_json_to_file(response, "years.json")  # сохраяеем данные запроса в файл (для теста)
yy = responseYears.json(object_hook=lambda d: SimpleNamespace(**d))[0]
print(f"\r\nИнформация доступна с {yy.FromYear} по {yy.ToYear} год")

FromYear = -1
ToYear = -1
while True:
    try:
        FromYear = int(input("Введите год начала периода:"))
        ToYear = int(input("Введите год окончания периода:"))
        if FromYear >= yy.FromYear and ToYear <= yy.ToYear:
            break
        else:
            print(f"\r\nИнформация доступна с {yy.FromYear} по {yy.ToYear} год")
    except ValueError:
        print("ошибка! год должен быть числом...")

    # Далее получаем массив данных
dataParams = {'y1': FromYear, 'y2': ToYear, 'publicationId': publId, 'datasetId': dsId, "measureId": melId}
responseData = requests.get(f"{BASE_URL}/data", params=dataParams)
save_json_to_file(responseData, "data.json")  # сохраяеем данные запроса в файл (для теста)
export_data_to_csv(responseData.json(object_hook=lambda d: SimpleNamespace(**d)))

print("All done...")
