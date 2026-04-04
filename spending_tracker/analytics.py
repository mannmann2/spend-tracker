import pandas as pd


def filter_transactions(
    df: pd.DataFrame,
    start_date,
    end_date,
    categories: list[str],
    accounts: list[str],
    directions: list[str],
    include_transfers: bool = False,
) -> pd.DataFrame:
    if df.empty:
        return df

    filtered = df.copy()
    if start_date:
        filtered = filtered[filtered["txn_date"].dt.date >= start_date]
    if end_date:
        filtered = filtered[filtered["txn_date"].dt.date <= end_date]
    if categories:
        filtered = filtered[filtered["category"].isin(categories)]
    if accounts:
        filtered = filtered[filtered["account"].isin(accounts)]
    if directions:
        filtered = filtered[filtered["direction"].isin(directions)]
    if not include_transfers:
        filtered = filtered[~filtered["category"].fillna("").str.lower().isin(["transfer", "transfers"])]
    return filtered


def aggregate_transactions(df: pd.DataFrame, group_by: list[str]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=group_by + ["amount"])
    aggregated = (
        df.groupby(group_by, dropna=False)["signed_amount"]
        .sum()
        .reset_index()
        .rename(columns={"signed_amount": "amount"})
    )
    return aggregated.sort_values(group_by)
