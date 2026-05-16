//! Helpers for reading OpenTelemetry protobuf attribute values.

use opentelemetry_proto::tonic::common::v1::{any_value::Value, AnyValue, KeyValue};
use serde_json::{Map, Number, Value as Json};

pub fn any_to_json(v: &AnyValue) -> Json {
    match &v.value {
        Some(Value::StringValue(s)) => Json::String(s.clone()),
        Some(Value::BoolValue(b)) => Json::Bool(*b),
        Some(Value::IntValue(i)) => Json::Number((*i).into()),
        Some(Value::DoubleValue(d)) => Number::from_f64(*d)
            .map(Json::Number)
            .unwrap_or(Json::Null),
        Some(Value::BytesValue(b)) => Json::String(hex::encode(b)),
        Some(Value::ArrayValue(a)) => {
            Json::Array(a.values.iter().map(any_to_json).collect())
        }
        Some(Value::KvlistValue(kv)) => Json::Object(attrs_map(&kv.values)),
        None => Json::Null,
    }
}

pub fn attrs_map(attrs: &[KeyValue]) -> Map<String, Json> {
    let mut m = Map::with_capacity(attrs.len());
    for kv in attrs {
        let val = kv.value.as_ref().map(any_to_json).unwrap_or(Json::Null);
        m.insert(kv.key.clone(), val);
    }
    m
}

pub fn get_str<'a>(attrs: &'a [KeyValue], key: &str) -> Option<&'a str> {
    attrs.iter().find(|k| k.key == key).and_then(|k| {
        match &k.value.as_ref()?.value {
            Some(Value::StringValue(s)) => Some(s.as_str()),
            _ => None,
        }
    })
}

pub fn get_i64(attrs: &[KeyValue], key: &str) -> Option<i64> {
    attrs.iter().find(|k| k.key == key).and_then(|k| {
        match &k.value.as_ref()?.value {
            Some(Value::IntValue(i)) => Some(*i),
            Some(Value::StringValue(s)) => s.parse().ok(),
            _ => None,
        }
    })
}

pub fn get_f64(attrs: &[KeyValue], key: &str) -> Option<f64> {
    attrs.iter().find(|k| k.key == key).and_then(|k| {
        match &k.value.as_ref()?.value {
            Some(Value::DoubleValue(d)) => Some(*d),
            Some(Value::IntValue(i)) => Some(*i as f64),
            Some(Value::StringValue(s)) => s.parse().ok(),
            _ => None,
        }
    })
}

pub fn get_bool(attrs: &[KeyValue], key: &str) -> Option<bool> {
    attrs.iter().find(|k| k.key == key).and_then(|k| {
        match &k.value.as_ref()?.value {
            Some(Value::BoolValue(b)) => Some(*b),
            Some(Value::StringValue(s)) => s.parse().ok(),
            _ => None,
        }
    })
}
