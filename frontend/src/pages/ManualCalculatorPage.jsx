import React, { useState, useEffect } from 'react';
import { ArrowLeft, Calculator, AlertTriangle, RefreshCw } from 'lucide-react';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';

// Utility for safe parsing
const safeFloat = (val) => {
    const parsed = parseFloat(val);
    return isNaN(parsed) ? 0 : parsed;
};

const ManualCalculatorPage = () => {
    // State
    const [glucose, setGlucose] = useState('');
    const [carbs, setCarbs] = useState('');
    const [target, setTarget] = useState('110'); // Default safer target
    const [isf, setIsf] = useState('50'); // Default guess
    const [icr, setIcr] = useState('10'); // Default guess
    const [iob, setIob] = useState('0');
    
    const [result, setResult] = useState(null);

    // Calculate on change
    useEffect(() => {
        calculate();
    }, [glucose, carbs, target, isf, icr, iob]);

    const calculate = () => {
        const g = safeFloat(glucose);
        const c = safeFloat(carbs);
        const t = safeFloat(target);
        const sens = safeFloat(isf);
        const ratio = safeFloat(icr);
        const active = safeFloat(iob);

        if (sens === 0 || ratio === 0) {
            setResult(null);
            return;
        }

        const correction = (g - t) / sens;
        const meal = c / ratio;
        const gross = correction + meal;
        const net = gross - active;

        setResult({
            correction: Math.max(0, correction), // Visual component
            meal: meal,
            gross: gross,
            net: Math.max(0, net), // Never recommend negative
            raw_net: net // For debugging
        });
    };

    return (
        <div className="p-4 space-y-4 max-w-lg mx-auto pb-24">
            {/* Header */}
            <div className="flex items-center space-x-2">
                <Button variant="ghost" size="icon" onClick={() => window.history.back()}>
                    <ArrowLeft size={24} />
                </Button>
                <h1 className="text-xl font-bold flex items-center text-red-600">
                    <AlertTriangle size={20} className="mr-2" />
                    Calculadora de Emergencia
                </h1>
            </div>

            <div className="bg-red-50 border border-red-200 p-3 rounded-lg text-sm text-red-800">
                <p>⚠️ <strong>Modo Offline/Manual:</strong> Esta calculadora NO usa internet ni conecta con Nightscout. Tú eres responsable de introducir los datos correctos.</p>
            </div>

            <Card className="p-4 space-y-4">
                <div className="grid grid-cols-2 gap-4">
                    {/* Glucose */}
                    <div className="space-y-1">
                        <label className="text-xs font-bold text-gray-500 uppercase">Glucosa (mg/dL)</label>
                        <input 
                            type="number" 
                            className="w-full text-2xl font-bold p-2 border rounded border-gray-300 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
                            placeholder="ej. 150"
                            value={glucose}
                            onChange={(e) => setGlucose(e.target.value)}
                        />
                    </div>

                    {/* Carbs */}
                    <div className="space-y-1">
                        <label className="text-xs font-bold text-gray-500 uppercase">Carbohidratos (g)</label>
                        <input 
                            type="number" 
                            className="w-full text-2xl font-bold p-2 border rounded border-gray-300 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
                            placeholder="ej. 45"
                            value={carbs}
                            onChange={(e) => setCarbs(e.target.value)}
                        />
                    </div>
                </div>

                {/* Factors */}
                <div className="pt-2 border-t border-gray-100 grid grid-cols-3 gap-3">
                    <div className="space-y-1">
                        <label className="text-[10px] font-bold text-gray-400 uppercase">Objetivo</label>
                        <input 
                            type="number" 
                            className="w-full text-lg font-medium p-1 border rounded bg-gray-50"
                            value={target}
                            onChange={(e) => setTarget(e.target.value)}
                        />
                    </div>
                    <div className="space-y-1">
                        <label className="text-[10px] font-bold text-gray-400 uppercase">ISF (Sensib.)</label>
                        <input 
                            type="number" 
                            className="w-full text-lg font-medium p-1 border rounded bg-gray-50"
                            value={isf}
                            onChange={(e) => setIsf(e.target.value)}
                        />
                    </div>
                    <div className="space-y-1">
                        <label className="text-[10px] font-bold text-gray-400 uppercase">ICR (Ratio)</label>
                        <input 
                            type="number" 
                            className="w-full text-lg font-medium p-1 border rounded bg-gray-50"
                            value={icr}
                            onChange={(e) => setIcr(e.target.value)}
                        />
                    </div>
                </div>

                <div className="space-y-1">
                     <label className="text-[10px] font-bold text-gray-400 uppercase">IOB (Insulina Activa Restante)</label>
                     <input 
                         type="number" 
                         className="w-full text-lg font-medium p-1 border rounded bg-gray-50"
                         placeholder="0.0"
                         value={iob}
                         onChange={(e) => setIob(e.target.value)}
                     />
                     <span className="text-[10px] text-gray-400">Si no sabes, deja 0 (más conservador si glucosa alta, arriesgado si acabas de ponerte insulina).</span>
                </div>
            </Card>

            {/* Result */}
            <Card className="p-4 bg-gray-900 text-white">
                <div className="flex justify-between items-end mb-4">
                    <div>
                        <h2 className="text-gray-400 text-sm font-medium">Bolo Total Sugerido</h2>
                        {result && result.raw_net < 0 && (
                             <span className="text-xs text-yellow-500 block mt-1">IOB cubre corrección y comida</span>
                        )}
                    </div>
                    <div className="text-5xl font-bold tracking-tighter text-blue-400">
                        {result ? result.net.toFixed(2) : "---"} <span className="text-xl text-gray-500">U</span>
                    </div>
                </div>

                {result && (
                    <div className="border-t border-gray-700 pt-3 space-y-2 text-sm text-gray-300">
                        <div className="flex justify-between">
                            <span>Corrección (({glucose || 0} - {target}) / {isf})</span>
                            <span>{result.correction.toFixed(2)} U</span>
                        </div>
                        <div className="flex justify-between">
                            <span>Comida ({carbs || 0} / {icr})</span>
                            <span>{result.meal.toFixed(2)} U</span>
                        </div>
                        <div className="flex justify-between text-gray-500">
                            <span>IOB Restado</span>
                            <span>- {safeFloat(iob).toFixed(2)} U</span>
                        </div>
                    </div>
                )}
            </Card>

            <Button 
                variant="outline" 
                className="w-full py-6 text-lg"
                onClick={() => {
                    setGlucose('');
                    setCarbs('');
                    setIob('0');
                }}
            >
                <RefreshCw size={20} className="mr-2" />
                Limpiar Datos
            </Button>
        </div>
    );
};

export default ManualCalculatorPage;
