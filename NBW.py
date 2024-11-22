import requests
import json
import logging
from collections import Counter

# Configure logging
logging.basicConfig(level=logging.INFO)

application_id = [22019]  # Add more IDs as needed


# API URLs for BNPL, Wage Advance, and Non-SACC Loans
API_URLS = {
    "BNPL": "https://app.cashfaster.com.au/bank-statement/get-factor/bnpl",
    "Wage Advance": "https://app.cashfaster.com.au/bank-statement/get-factor/wages_advance",
    "Non-SACC Loans": "https://app.cashfaster.com.au/bank-statement/get-factor/non_sacc_loans",
}

# 1. Data Extraction
def fetch_data(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Data extraction failed for URL {url}: {e}")
        return None

# 2. Define Income and Expense Categories
income_categories = {
    "Wages - Monthly": "Wages",
    "Centrelink - Monthly": "Centrelink",
}

expense_categories = {
    "SACC Loans - Monthly": "SACC",
    "Debt Collection - Monthly": "Debt Collection",
}

# Initialize category totals
def initialize_category_totals():
    category_totals = {label: 0.0 for label in income_categories.values()}
    category_totals.update({label: 0.0 for label in expense_categories.values()})
    category_totals["Living Expenses"] = 0.0
    category_totals["BNPL"] = 0.0
    category_totals["Wage Advance"] = 0.0
    category_totals["Non-SACC Loans"] = 0.0
    return category_totals

# 3. Parse and Clean Data
def parse_statement_analysis(raw_data):
    bank_accounts = raw_data.get("illionBankAccount", [])
    all_analyses = []
    for account in bank_accounts:
        statement_analysis_str = account.get("statementAnalysis", "[]")
        try:
            statement_analysis = json.loads(statement_analysis_str)
            if isinstance(statement_analysis, list):
                all_analyses.extend(statement_analysis)
        except json.JSONDecodeError:
            logging.error("Failed to parse statement analysis.")
            continue
    return all_analyses

# 4. Fetch third-party keywords for BNPL, Wage Advance, and Non-SACC Loans
def fetch_keywords(category):
    api_url = API_URLS.get(category)
    if not api_url:
        return []
    try:
        response = requests.get(api_url)
        response.raise_for_status()
        data = response.json().get("data", [])
        return data
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to fetch keywords for {category}: {e}")
        return []

# 5. Calculate BNPL, Wage Advance, and Non-SACC Loans
def calculate_category_totals(statement_analysis, category):
    third_party_keywords = fetch_keywords(category)
    if not third_party_keywords:
        logging.info(f"No keywords found for {category}. Skipping calculation.")
        return 0.0

    total_amount = 0.0
    for entry in statement_analysis:
        if not isinstance(entry, dict):
            continue

        analysis_category = entry.get("analysisCategory", {})
        if analysis_category.get("name") != category:
            continue

        for group in analysis_category.get("transactionGroups", []):
            third_party = group.get("name", "")
            if third_party not in third_party_keywords:
                continue

            transactions = group.get("transactions", [])
            if isinstance(transactions, str):
                try:
                    transactions = json.loads(transactions)
                except json.JSONDecodeError:
                    logging.error("Failed to parse transactions JSON.")
                    continue

            for transaction in transactions:
                amount = transaction.get("amount", 0)
                if isinstance(amount, (int, float)) and amount > 0:
                    total_amount += amount

    return total_amount

# 6. Accumulate Metrics from Statement Analysis
def accumulate_metrics(statement_analysis, category_totals):
    logging.info("Calculating BNPL, Wage Advance, and Non-SACC Loans...")
    category_totals["BNPL"] = calculate_category_totals(statement_analysis, "BNPL")
    category_totals["Wage Advance"] = calculate_category_totals(statement_analysis, "Wage Advance")
    category_totals["Non-SACC Loans"] = calculate_category_totals(statement_analysis, "Non-SACC Loans")
    logging.info(f"BNPL Total: ${category_totals['BNPL']:.2f}")
    logging.info(f"Wage Advance Total: ${category_totals['Wage Advance']:.2f}")
    logging.info(f"Non-SACC Loans Total: ${category_totals['Non-SACC Loans']:.2f}")

# 7. Main Logic
def main():
    all_outputs = []
    for loan_id in application_id:
        url = f"https://admin.cashfaster.com.au/bank-statement/{loan_id}"
        raw_data = fetch_data(url)
        if raw_data is None:
            continue

        statement_analysis = parse_statement_analysis(raw_data)
        category_totals = initialize_category_totals()
        accumulate_metrics(statement_analysis, category_totals)

        # Generate and save output
        output = f"""
        Loan ID: {loan_id}
        BNPL: ${category_totals["BNPL"]:.2f}
        Wage Advance: ${category_totals["Wage Advance"]:.2f}
        Non-SACC Loans: ${category_totals["Non-SACC Loans"]:.2f}
        """
        all_outputs.append(output)
        logging.info(output)

    try:
        with open("output.txt", "w") as file:
            file.writelines(all_outputs)
        logging.info("Results saved to output.txt")
    except IOError as e:
        logging.error(f"Failed to save results: {e}")

if __name__ == "__main__":
    main()
