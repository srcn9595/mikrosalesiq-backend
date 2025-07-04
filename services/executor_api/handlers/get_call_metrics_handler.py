# handlers/get_call_metrics_handler.py

def get_call_metrics_handler(db, metrics_steps):
    results = []

    # ❶ Müşteri numarası veya müşteri numaraları (liste) normalize et
    customer_set = set()
    for st in metrics_steps:
        arg = st.get("arguments", {})
        if "customer_num" in arg:
            customer_set.add(arg["customer_num"])
        if "customer_nums" in arg:
            customer_set.update(arg["customer_nums"])

    # ❷ Her müşteri numarası için metrikleri hesapla
    for cnum in customer_set:
        pipeline = [
            {"$unwind": "$calls"},
            {"$match": {"customer_num": cnum}},
            {"$group": {
                "_id": "$customer_num",
                "total_calls": {"$sum": 1},
                "avg_duration": {"$avg": "$calls.duration"},
                "max_duration": {"$max": "$calls.duration"},
                "unique_agents": {"$addToSet": "$calls.agent_email"}
            }},
            {"$project": {
                "_id": 0,
                "customer_num": "$_id",
                "total_calls": 1,
                "avg_duration": 1,
                "max_duration": 1,
                "unique_agents_count": {"$size": "$unique_agents"}
            }}
        ]

        metrics = list(db["audio_jobs"].aggregate(pipeline))
        if metrics:
            results.append({"name": "get_call_metrics", "output": metrics[0]})
        else:
            results.append({
                "name": "get_call_metrics",
                "output": {"message": f"{cnum} için metrik verisi bulunamadı."}
            })
    return results
