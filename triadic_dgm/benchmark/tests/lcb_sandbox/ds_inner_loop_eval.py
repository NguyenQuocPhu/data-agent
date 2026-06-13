import pandas as pd

def main():
    # Verifier Feedback: Update file_path variable to point to the correct absolute or relative path
    file_path = 'sales_data.csv'

    # 1. Load the sales_data.csv file into a structured data format
    df = pd.read_csv(file_path)

    # 2. Identify all missing values in the 'sales' column
    # 3. Compute the arithmetic mean of non-missing 'sales' values
    mean_sales = df['sales'].mean()

    # 4. Replace each missing 'sales' value with the computed mean
    df['sales'] = df['sales'].fillna(mean_sales)

    # 5. Group the dataset by the 'region' column
    # 6. Calculate the sum of 'sales' for each region group
    regional_sales = df.groupby('region')['sales'].sum()

    # Output the results
    print(regional_sales)

if __name__ == '__main__':
    main()
