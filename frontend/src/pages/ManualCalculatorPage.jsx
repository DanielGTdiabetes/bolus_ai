import React, { useEffect, useState } from 'react';
import { ArrowLeft, AlertTriangle, RefreshCw } from 'lucide-react';
import { Card, Button } from '../components/ui/Atoms';
import { calculateManualBolus } from '../lib/manualBolusCore';
import { getCalcParams } from '../modules/core/store';

const MEAL_SLOTS = [
    ['breakfast', 'Desayuno'],
    ['lunch', 'Comida'],
    ['dinner', 'Cena'],
    ['snack', 'Snack'],
];

const ManualCalculatorPage = () => {
    const [glucose, setGlucose] = useState('');
    const [carbs, setCarbs] = useState('');
    const [target, setTarget] = useState('');
    const [isf, setIsf] = useState('');
    const [icr, setIcr] = useState('');
    const [iob, setIob] = useState('');
    const [maxBolus, setMaxBolus] = useState('15');
    const [roundStep, setRoundStep] = useState('0.05');
    const [mealSlot, setMealSlot] = useState('lunch');
    const [storedParams, setStoredParams] = useState(null);

    const [result, setResult] = useState(null);
    const [error, setError] = useState('');

    useEffect(() => {
        const params = getCalcParams();
        setStoredParams(params || null);

        if (params?.max_bolus_u) setMaxBolus(String(params.max_bolus_u));
        if (params?.round_step_u) setRoundStep(String(params.round_step_u));
    }, []);

    useEffect(() => {
        const slotParams = storedParams?.[mealSlot];
        if (!slotParams) return;

        if (slotParams.target !== undefined && slotParams.target !== null) {
            setTarget(String(slotParams.target));
        }
        if (slotParams.isf !== undefined && slotParams.isf !== null) {
            setIsf(String(slotParams.isf));
        }
        if (slotParams.icr !== undefined && slotParams.icr !== null) {
            setIcr(String(slotParams.icr));
        }
    }, [storedParams, mealSlot]);

    useEffect(() => {
        if ([glucose, carbs, target, isf, icr, iob].some((value) => value === '')) {
            setResult(null);
            setError('');
            return;
        }

        try {
            const next = calculateManualBolus({
                glucose,
                carbs,
                target,
                isf,
                icr,
                iob,
                maxBolus,
                roundStep,
            });
            setResult(next);
            setError('');
        } catch (err) {
            setResult(null);
            setError(err?.message || 'Datos no válidos.');
        }
    }, [glucose, carbs, target, isf, icr, iob, maxBolus, roundStep]);

    const reset = () => {
        setGlucose('');
        setCarbs('');
        setIob('');
        setResult(null);
        setError('');
    };

    return (
        <div className="p-4 space-y-4 max-w-lg mx-auto pb-24">
            <div className="flex items-center space-x-2">
                <Button variant="ghost" size="icon" onClick={() => window.history.back()}>
                    <ArrowLeft size={24} />
                </Button>
                <h1 className="text-xl font-bold flex items-center text-red-600">
                    <AlertTriangle size={20} className="mr-2" />
                    Calculadora de emergencia
                </h1>
            </div>

            <div className="bg-red-50 border border-red-200 p-3 rounded-lg text-sm text-red-800 space-y-2">
                <p><strong>Modo offline:</strong> funciona sin red y no consulta Nightscout, CGM, Autosens, ejercicio ni otros ajustes dinámicos.</p>
                <p>Los parámetros se cargan desde la última configuración guardada en este dispositivo cuando existe. Puedes revisarlos o modificarlos manualmente.</p>
                <p>Los hidratos son <strong>hidratos nuevos que quieres cubrir ahora</strong>. El IOB es obligatorio: escribe 0 únicamente si sabes que no tienes insulina rápida activa.</p>
            </div>

            <Card className="p-4 space-y-4">
                <div className="space-y-1">
                    <label className="text-xs font-bold text-gray-500 uppercase">Perfil horario</label>
                    <select
                        className="w-full p-2 border rounded border-gray-300 bg-white"
                        value={mealSlot}
                        onChange={(e) => setMealSlot(e.target.value)}
                    >
                        {MEAL_SLOTS.map(([value, label]) => (
                            <option key={value} value={value}>{label}</option>
                        ))}
                    </select>
                    <span className="text-[10px] text-gray-400">
                        {storedParams?.[mealSlot]
                            ? 'ICR, ISF y objetivo cargados desde la última configuración local.'
                            : 'No hay parámetros guardados para este horario. Introdúcelos manualmente.'}
                    </span>
                </div>

                <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-1">
                        <label className="text-xs font-bold text-gray-500 uppercase">Glucosa (mg/dL)</label>
                        <input
                            type="number"
                            min="40"
                            max="400"
                            className="w-full text-2xl font-bold p-2 border rounded border-gray-300 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
                            placeholder="ej. 150"
                            value={glucose}
                            onChange={(e) => setGlucose(e.target.value)}
                        />
                    </div>

                    <div className="space-y-1">
                        <label className="text-xs font-bold text-gray-500 uppercase">HC nuevos (g)</label>
                        <input
                            type="number"
                            min="0"
                            max="500"
                            className="w-full text-2xl font-bold p-2 border rounded border-gray-300 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
                            placeholder="ej. 45"
                            value={carbs}
                            onChange={(e) => setCarbs(e.target.value)}
                        />
                    </div>
                </div>

                <div className="pt-2 border-t border-gray-100 grid grid-cols-3 gap-3">
                    <div className="space-y-1">
                        <label className="text-[10px] font-bold text-gray-400 uppercase">Objetivo</label>
                        <input
                            type="number"
                            min="60"
                            max="250"
                            placeholder="obligatorio"
                            className="w-full text-lg font-medium p-1 border rounded bg-gray-50"
                            value={target}
                            onChange={(e) => setTarget(e.target.value)}
                        />
                    </div>
                    <div className="space-y-1">
                        <label className="text-[10px] font-bold text-gray-400 uppercase">ISF</label>
                        <input
                            type="number"
                            min="5"
                            max="500"
                            placeholder="obligatorio"
                            className="w-full text-lg font-medium p-1 border rounded bg-gray-50"
                            value={isf}
                            onChange={(e) => setIsf(e.target.value)}
                        />
                    </div>
                    <div className="space-y-1">
                        <label className="text-[10px] font-bold text-gray-400 uppercase">ICR</label>
                        <input
                            type="number"
                            min="1"
                            max="200"
                            placeholder="obligatorio"
                            className="w-full text-lg font-medium p-1 border rounded bg-gray-50"
                            value={icr}
                            onChange={(e) => setIcr(e.target.value)}
                        />
                    </div>
                </div>

                <div className="grid grid-cols-3 gap-3">
                    <div className="space-y-1">
                        <label className="text-[10px] font-bold text-gray-400 uppercase">IOB (U)</label>
                        <input
                            type="number"
                            min="0"
                            max="30"
                            step="0.05"
                            className="w-full text-lg font-medium p-1 border rounded bg-gray-50"
                            placeholder="obligatorio"
                            value={iob}
                            onChange={(e) => setIob(e.target.value)}
                        />
                    </div>
                    <div className="space-y-1">
                        <label className="text-[10px] font-bold text-gray-400 uppercase">Máx. bolo</label>
                        <input
                            type="number"
                            min="0.05"
                            max="50"
                            step="0.05"
                            className="w-full text-lg font-medium p-1 border rounded bg-gray-50"
                            value={maxBolus}
                            onChange={(e) => setMaxBolus(e.target.value)}
                        />
                    </div>
                    <div className="space-y-1">
                        <label className="text-[10px] font-bold text-gray-400 uppercase">Redondeo</label>
                        <input
                            type="number"
                            min="0.01"
                            max="1"
                            step="0.01"
                            className="w-full text-lg font-medium p-1 border rounded bg-gray-50"
                            value={roundStep}
                            onChange={(e) => setRoundStep(e.target.value)}
                        />
                    </div>
                </div>
            </Card>

            {error && (
                <div className="bg-yellow-50 border border-yellow-300 p-3 rounded-lg text-sm text-yellow-900">
                    {error}
                </div>
            )}

            <Card className="p-4 bg-gray-900 text-white">
                <div className="flex justify-between items-end mb-4">
                    <div>
                        <h2 className="text-gray-400 text-sm font-medium">Bolo total sugerido</h2>
                        {result?.hardStop && (
                            <span className="text-xs text-red-400 block mt-1">Bloqueado por glucosa &lt;70 mg/dL</span>
                        )}
                        {result?.clamped && (
                            <span className="text-xs text-yellow-400 block mt-1">Limitado por bolo máximo manual</span>
                        )}
                    </div>
                    <div className="text-5xl font-bold tracking-tighter text-blue-400">
                        {result ? result.total.toFixed(2) : '---'} <span className="text-xl text-gray-500">U</span>
                    </div>
                </div>

                {result && (
                    <div className="border-t border-gray-700 pt-3 space-y-2 text-sm text-gray-300">
                        <div className="flex justify-between">
                            <span>Comida ({result.carbs.toFixed(1)} g / {result.icr.toFixed(1)})</span>
                            <span>{result.meal.toFixed(2)} U</span>
                        </div>
                        <div className="flex justify-between">
                            <span>Corrección teórica</span>
                            <span>{result.rawCorrection.toFixed(2)} U</span>
                        </div>
                        {result.lowBgAdjustment < 0 && (
                            <div className="flex justify-between text-yellow-300">
                                <span>Ajuste por glucosa baja</span>
                                <span>{result.lowBgAdjustment.toFixed(2)} U</span>
                            </div>
                        )}
                        <div className="flex justify-between">
                            <span>Corrección positiva</span>
                            <span>{result.positiveCorrection.toFixed(2)} U</span>
                        </div>
                        <div className="flex justify-between text-gray-400">
                            <span>IOB aplicado a corrección</span>
                            <span>{Math.min(result.iob, result.positiveCorrection).toFixed(2)} U</span>
                        </div>
                        <div className="flex justify-between">
                            <span>Corrección tras IOB</span>
                            <span>{result.correctionAfterIob.toFixed(2)} U</span>
                        </div>
                        <div className="flex justify-between text-gray-400">
                            <span>Antes de redondeo</span>
                            <span>{result.rawTotal.toFixed(2)} U</span>
                        </div>
                        {result.warning && (
                            <div className="pt-2 text-xs text-yellow-300">{result.warning}</div>
                        )}
                    </div>
                )}
            </Card>

            <Button
                variant="outline"
                className="w-full py-6 text-lg"
                onClick={reset}
            >
                <RefreshCw size={20} className="mr-2" />
                Limpiar datos
            </Button>
        </div>
    );
};

export default ManualCalculatorPage;
